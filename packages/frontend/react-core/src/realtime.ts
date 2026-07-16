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
  /** Runtime validation for the channel's Pydantic JSON wire payload. */
  validate(value: unknown): value is Message;
  /** Receive every validated message (lastMessage is also retained). */
  onMessage?(message: Message): void;
  /** Default true; false closes/does not open the transport. */
  enabled?: boolean;
}

export interface RealtimeChannelState<Message> {
  status: RealtimeStatus;
  lastMessage: Message | null;
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
): Message {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    throw new Error("Realtime channel received invalid JSON");
  }
  if (!validate(value)) {
    throw new Error("Realtime channel received a payload outside its declared type");
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
  const terminalFailureRef = useRef<(cause: unknown) => void>(() => {});
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
      const message = parseMessage(raw, validateRef.current);
      setLastMessage(message);
      onMessageRef.current?.(message);
    } catch (cause) {
      terminalFailureRef.current(cause);
    }
  };

  const failRef = useRef((cause: unknown) => {});
  failRef.current = (cause: unknown) => {
    setError(cause instanceof Error ? cause : new Error("Realtime connection failed"));
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

    const terminalFailure = (cause: unknown) => {
      if (!active()) return;
      stopped = true;
      cancelRetry();
      releaseTransport("invalid message payload");
      failRef.current(cause);
    };
    terminalFailureRef.current = terminalFailure;

    if (!enabled) {
      stopped = true;
      setStatus("closed");
      return () => {
        cancelled = true;
        if (closeRef.current === stop) closeRef.current = () => {};
        if (terminalFailureRef.current === terminalFailure) {
          terminalFailureRef.current = () => {};
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
      if (terminalFailureRef.current === terminalFailure) {
        terminalFailureRef.current = () => {};
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
