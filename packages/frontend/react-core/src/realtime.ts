import { useEffect, useRef, useState } from "react";

import { useTerpBaseUrl, useTerpClient } from "./TerpProvider";

export type RealtimeTransport = "sse" | "websocket";
export type RealtimeStatus = "connecting" | "open" | "closed" | "error";

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
      setError(cause instanceof Error ? cause : new Error("Realtime message failed"));
      setStatus("error");
      socketRef.current?.close(1003, "invalid message payload");
      eventSourceRef.current?.close();
    }
  };

  const failRef = useRef((cause: unknown) => {});
  failRef.current = (cause: unknown) => {
    setError(cause instanceof Error ? cause : new Error("Realtime connection failed"));
    setStatus("error");
  };

  useEffect(() => {
    let cancelled = false;
    let source: EventSource | null = null;
    let socket: WebSocket | null = null;
    if (!enabled) {
      setStatus("closed");
      return;
    }
    setStatus("connecting");
    setError(null);

    void client
      .POST("/api/v1/realtime/tickets", {
        body: { channel, transport },
      })
      .then(({ data, error: apiError }) => {
        if (cancelled) return;
        if (apiError || !data) {
          throw new Error("Realtime ticket mint failed");
        }
        const url = transportUrl(baseUrl, transport, channel, data.ticket);
        if (transport === "sse") {
          source = new EventSource(url);
          eventSourceRef.current = source;
          source.onopen = () => setStatus("open");
          source.onmessage = (event) => receiveRef.current(event.data);
          source.onerror = () =>
            failRef.current(new Error("Realtime SSE connection failed"));
        } else {
          socket = new WebSocket(url);
          socketRef.current = socket;
          socket.onopen = () => setStatus("open");
          socket.onmessage = (event) => receiveRef.current(String(event.data));
          socket.onerror = () =>
            failRef.current(new Error("Realtime WebSocket connection failed"));
          socket.onclose = () => {
            socketRef.current = null;
            setStatus((current) => (current === "error" ? current : "closed"));
          };
        }
      })
      .catch((cause) => {
        if (!cancelled) failRef.current(cause);
      });

    return () => {
      cancelled = true;
      source?.close();
      socket?.close(1000, "component unmounted");
      if (eventSourceRef.current === source) eventSourceRef.current = null;
      if (socketRef.current === socket) socketRef.current = null;
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
      eventSourceRef.current?.close();
      socketRef.current?.close(1000, "closed by caller");
      eventSourceRef.current = null;
      socketRef.current = null;
      setStatus("closed");
    },
  };
}

export { parseMessage, transportUrl };
