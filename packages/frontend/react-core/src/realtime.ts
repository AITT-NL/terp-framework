import { useEffect, useRef, useState } from "react";

import { useTerpBaseUrl, useTerpClient } from "./TerpProvider";

export type RealtimeTransport = "sse" | "websocket";
export type RealtimeStatus = "connecting" | "open" | "closed" | "error";

const INITIAL_RECONNECT_DELAY_MS = 1_000;
const MAX_RECONNECT_DELAY_MS = 30_000;

interface TicketResponse {
  ticket: string;
  expires_in: number;
  channel: string;
  transport: RealtimeTransport;
}

interface RealtimePaths {
  "/api/v1/realtime/tickets": {
    post: {
      requestBody: {
        content: {
          "application/json": {
            channel: string;
            transport: RealtimeTransport;
          };
        };
      };
      responses: {
        201: { content: { "application/json": TicketResponse } };
      };
    };
  };
}

export interface RealtimeChannelOptions<Message> {
  channel: string;
  transport?: RealtimeTransport;
  /**
   * Runtime validation for the channel's Pydantic JSON wire payload.
   *
   * THIS FUNCTION IS THE DRIFT BOUNDARY. The authoritative shape is the server's
   * `RealtimeChannel.outbound_model`, which the backend validates every publish against;
   * this guard is hand-written client-side code asserting the same thing. Nothing checks
   * the two against each other, so the realistic way this guard fails is not an attack —
   * the payload's only author is the same deployment's own backend, behind a one-use
   * ticket — but a field added or an enum member widened on the server while the guard
   * still describes the old shape.
   *
   * Because that is the realistic cause, a payload this guard rejects is treated as a
   * MESSAGE failure and not a transport failure: the message is dropped, the rejection is
   * surfaced once on `error` naming this channel, and the transport stays open and keeps
   * delivering. Write the guard narrowly enough to be worth having and wide enough that a
   * server-side addition does not silently blank a screen.
   */
  validate(value: unknown): value is Message;
  /** Receive every validated message (lastMessage is also retained). */
  onMessage?(message: Message): void;
  /** Default true; false closes/does not open the transport. */
  enabled?: boolean;
}

export interface RealtimeChannelState<Message> {
  /**
   * The transport's state. `"error"` means the transport itself failed and a reconnect is
   * scheduled; a message the guard rejected does NOT move this away from `"open"`.
   */
  status: RealtimeStatus;
  lastMessage: Message | null;
  /**
   * The most recent failure, which is not the same question as `status`. A rejected
   * payload sets this while `status` stays `"open"`: the channel is still delivering, and
   * something it was sent did not match the declared type. Read the pair, not either half
   * — `status === "error"` is the connection's verdict, `error !== null` is the last
   * reason of any kind.
   */
  error: Error | null;
  /** WebSocket only; throws unless the socket is open. */
  send(message: unknown): void;
  close(): void;
}

function httpBase(baseUrl: string): URL {
  const browserBase =
    typeof window === "undefined" ? "http://localhost/" : window.location.href;
  return new URL(baseUrl || "/", browserBase);
}

function transportUrl(
  baseUrl: string,
  transport: RealtimeTransport,
  channel: string,
  ticket: string,
): string {
  const base = httpBase(baseUrl);
  const kind = transport === "sse" ? "sse" : "ws";
  const url = new URL(
    `/api/v1/realtime/${kind}/${encodeURIComponent(channel)}`,
    base,
  );
  if (transport === "websocket") {
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  }
  url.searchParams.set("ticket", ticket);
  return url.toString();
}

function parseMessage<Message>(
  raw: string,
  validate: (value: unknown) => value is Message,
  channel?: string,
): Message {
  // The channel is named in the message because the reader of this error is debugging
  // drift between one server-side model and one hand-written guard, and an app may hold
  // several channels at once. Optional so the predicate stays callable on its own.
  const named = channel === undefined ? "Realtime channel" : `Realtime channel "${channel}"`;
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    throw new Error(`${named} received invalid JSON`);
  }
  if (!validate(value)) {
    throw new Error(`${named} received a payload outside its declared type`);
  }
  return value;
}

/**
 * Subscribe to one typed realtime channel through the sanctioned transport.
 *
 * The hook mints a 30-second, one-use ticket via the generated authenticated
 * client, then opens EventSource or WebSocket internally. App modules never
 * touch raw egress APIs, bearer tokens never enter URLs, and each inbound JSON
 * payload passes the caller's runtime type guard before reaching state/code.
 */
export function useRealtimeChannel<Message>({
  channel,
  transport = "sse",
  validate,
  onMessage,
  enabled = true,
}: RealtimeChannelOptions<Message>): RealtimeChannelState<Message> {
  const client = useTerpClient<RealtimePaths>();
  const baseUrl = useTerpBaseUrl();
  const socketRef = useRef<WebSocket | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const validateRef = useRef(validate);
  const onMessageRef = useRef(onMessage);
  const closeRef = useRef<() => void>(() => {});
  const messageFailureRef = useRef<(cause: unknown) => void>(() => {});
  validateRef.current = validate;
  onMessageRef.current = onMessage;
  const [status, setStatus] = useState<RealtimeStatus>(
    enabled ? "connecting" : "closed",
  );
  const [lastMessage, setLastMessage] = useState<Message | null>(null);
  const [error, setError] = useState<Error | null>(null);

  const receiveRef = useRef((raw: string) => {});
  receiveRef.current = (raw: string) => {
    try {
      const message = parseMessage(raw, validateRef.current, channel);
      setLastMessage(message);
      onMessageRef.current?.(message);
    } catch (cause) {
      // One message, one failure. The transport is fine — see `messageFailure`.
      messageFailureRef.current(cause);
    }
  };

  const reportRef = useRef((cause: unknown) => {});
  reportRef.current = (cause: unknown) => {
    setError(cause instanceof Error ? cause : new Error("Realtime channel failed"));
  };

  const failRef = useRef((cause: unknown) => {});
  failRef.current = (cause: unknown) => {
    reportRef.current(cause);
    setStatus("error");
  };

  useEffect(() => {
    let cancelled = false;
    let stopped = false;
    let source: EventSource | null = null;
    let socket: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let retryAttempt = 0;

    const active = () => !cancelled && !stopped;

    const releaseTransport = (reason: string) => {
      source?.close();
      socket?.close(1000, reason);
      if (eventSourceRef.current === source) eventSourceRef.current = null;
      if (socketRef.current === socket) socketRef.current = null;
      source = null;
      socket = null;
    };

    const cancelRetry = () => {
      if (retryTimer !== null) clearTimeout(retryTimer);
      retryTimer = null;
    };

    const stop = () => {
      stopped = true;
      cancelRetry();
      releaseTransport("closed by caller");
      setStatus("closed");
    };
    closeRef.current = stop;

    // A payload the guard rejects is a MESSAGE failure, not a transport failure.
    //
    // This used to tear the transport down: `stopped = true`, cancel the retry timer and
    // release the socket, which left the channel dead for the life of the mount — the
    // effect's deps never change on a bad message and the returned state exposes no reopen,
    // so neither shipped subscriber could recover. That is a self-inflicted outage in the
    // one case that actually happens: the payload's only author is the same deployment's
    // own backend behind a one-use ticket, so a guard miss means the hand-written guard has
    // fallen behind the server's model, and every LATER message — including the ones the
    // guard still accepts — was being discarded along with it.
    //
    // So: drop the message, say so once on `error` with the channel named, and keep
    // delivering. Once per connection, because a server whose shape has moved sends the
    // same wrong shape repeatedly and one re-render per message is a second failure on top
    // of the first; a reconnect clears the latch along with the error (`onopen`).
    let rejectedPayloadReported = false;
    const messageFailure = (cause: unknown) => {
      if (!active()) return;
      if (rejectedPayloadReported) return;
      rejectedPayloadReported = true;
      reportRef.current(cause);
    };
    messageFailureRef.current = messageFailure;

    if (!enabled) {
      stopped = true;
      setStatus("closed");
      return () => {
        cancelled = true;
        if (closeRef.current === stop) closeRef.current = () => {};
        if (messageFailureRef.current === messageFailure) {
          messageFailureRef.current = () => {};
        }
      };
    }
    setStatus("connecting");
    setError(null);
    setLastMessage(null);

    const connect = async (): Promise<void> => {
      if (!active()) return;
      setStatus("connecting");
      try {
        const { data, error: apiError } = await client.POST(
          "/api/v1/realtime/tickets",
          { body: { channel, transport } },
        );
        if (!active()) return;
        if (apiError || !data) {
          throw new Error("Realtime ticket mint failed");
        }
        const url = transportUrl(baseUrl, transport, channel, data.ticket);
        if (transport === "sse") {
          source = new EventSource(url);
          eventSourceRef.current = source;
          const connectedSource = source;
          source.onopen = () => {
            if (!active() || source !== connectedSource) return;
            retryAttempt = 0;
            rejectedPayloadReported = false;
            setError(null);
            setStatus("open");
          };
          source.onmessage = (event) => {
            if (!active() || source !== connectedSource) return;
            receiveRef.current(event.data);
          };
          source.onerror = () => {
            if (!active() || source !== connectedSource) return;
            scheduleReconnect(new Error("Realtime SSE connection failed"));
          };
        } else {
          socket = new WebSocket(url);
          socketRef.current = socket;
          const connectedSocket = socket;
          socket.onopen = () => {
            if (!active() || socket !== connectedSocket) return;
            retryAttempt = 0;
            rejectedPayloadReported = false;
            setError(null);
            setStatus("open");
          };
          socket.onmessage = (event) => {
            if (!active() || socket !== connectedSocket) return;
            receiveRef.current(String(event.data));
          };
          socket.onerror = () => {
            if (!active() || socket !== connectedSocket) return;
            scheduleReconnect(new Error("Realtime WebSocket connection failed"));
          };
          socket.onclose = (event) => {
            if (!active() || socket !== connectedSocket) return;
            scheduleReconnect(
              new Error(`Realtime WebSocket connection closed (${event.code})`),
            );
          };
        }
      } catch (cause) {
        if (active()) scheduleReconnect(cause);
      }
    };

    const scheduleReconnect = (cause: unknown) => {
      if (!active() || retryTimer !== null) return;
      releaseTransport("reconnecting");
      failRef.current(cause);
      const delay = Math.min(
        INITIAL_RECONNECT_DELAY_MS * 2 ** retryAttempt,
        MAX_RECONNECT_DELAY_MS,
      );
      retryAttempt += 1;
      retryTimer = setTimeout(() => {
        retryTimer = null;
        if (active()) void connect();
      }, delay);
    };

    void connect();

    return () => {
      cancelled = true;
      cancelRetry();
      releaseTransport("component unmounted");
      if (closeRef.current === stop) closeRef.current = () => {};
      if (messageFailureRef.current === messageFailure) {
        messageFailureRef.current = () => {};
      }
    };
  }, [baseUrl, channel, client, enabled, transport]);

  return {
    status,
    lastMessage,
    error,
    send(message: unknown) {
      const socket = socketRef.current;
      if (transport !== "websocket" || socket?.readyState !== WebSocket.OPEN) {
        throw new Error("Realtime WebSocket is not open");
      }
      socket.send(JSON.stringify(message));
    },
    close() {
      closeRef.current();
    },
  };
}

export { parseMessage, transportUrl };
