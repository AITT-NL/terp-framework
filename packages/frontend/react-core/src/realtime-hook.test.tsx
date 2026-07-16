// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  post: vi.fn(),
  client: null as unknown as { POST: ReturnType<typeof vi.fn> },
}));
mocks.client = { POST: mocks.post };

vi.mock("./TerpProvider", () => ({
  useTerpBaseUrl: () => "https://api.example.test",
  useTerpClient: () => mocks.client,
}));

import { useRealtimeChannel } from "./realtime";

interface Notice {
  sequence: number;
  text: string;
}

const isNotice = (value: unknown): value is Notice => {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return typeof record.sequence === "number" && typeof record.text === "string";
};

class EventSourceDouble {
  static instances: EventSourceDouble[] = [];

  readonly url: string;
  closed = false;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  constructor(url: string | URL) {
    this.url = String(url);
    EventSourceDouble.instances.push(this);
  }

  close() {
    this.closed = true;
  }
}

class WebSocketDouble {
  static readonly OPEN = 1;
  static instances: WebSocketDouble[] = [];

  readonly url: string;
  readyState = WebSocketDouble.OPEN;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;

  constructor(url: string | URL) {
    this.url = String(url);
    WebSocketDouble.instances.push(this);
  }

  send() {}

  close() {
    this.readyState = 3;
  }
}

afterEach(() => {
  cleanup();
  mocks.post.mockReset();
  EventSourceDouble.instances = [];
  WebSocketDouble.instances = [];
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("useRealtimeChannel lifecycle", () => {
  it("does not open a transport when closed while ticket mint is pending", async () => {
    let resolveTicket: ((value: unknown) => void) | undefined;
    mocks.post.mockReturnValue(
      new Promise((resolve) => {
        resolveTicket = resolve;
      }),
    );
    vi.stubGlobal("EventSource", EventSourceDouble);

    const { result } = renderHook(() =>
      useRealtimeChannel({ channel: "system.notices", validate: isNotice }),
    );
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));

    act(() => result.current.close());
    expect(result.current.status).toBe("closed");

    await act(async () => {
      resolveTicket?.({
        data: {
          ticket: "late-ticket",
          expires_in: 30,
          channel: "system.notices",
          transport: "sse",
        },
      });
      await Promise.resolve();
    });

    expect(EventSourceDouble.instances).toHaveLength(0);
    expect(result.current.status).toBe("closed");
  });

  it("closes a failed SSE source and remints its one-use ticket", async () => {
    vi.useFakeTimers();
    mocks.post
      .mockResolvedValueOnce({
        data: {
          ticket: "ticket-one",
          expires_in: 30,
          channel: "system.notices",
          transport: "sse",
        },
      })
      .mockResolvedValueOnce({
        data: {
          ticket: "ticket-two",
          expires_in: 30,
          channel: "system.notices",
          transport: "sse",
        },
      });
    vi.stubGlobal("EventSource", EventSourceDouble);

    const { result } = renderHook(() =>
      useRealtimeChannel({ channel: "system.notices", validate: isNotice }),
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(EventSourceDouble.instances).toHaveLength(1);
    expect(EventSourceDouble.instances[0].url).toContain("ticket=ticket-one");

    act(() => EventSourceDouble.instances[0].onerror?.(new Event("error")));
    expect(EventSourceDouble.instances[0].closed).toBe(true);
    expect(result.current.status).toBe("error");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
    });

    expect(mocks.post).toHaveBeenCalledTimes(2);
    expect(EventSourceDouble.instances).toHaveLength(2);
    expect(EventSourceDouble.instances[1].url).toContain("ticket=ticket-two");

    act(() =>
      EventSourceDouble.instances[0].onmessage?.(
        new MessageEvent("message", {
          data: '{"sequence":1,"text":"stale"}',
        }),
      ),
    );
    expect(result.current.lastMessage).toBeNull();

    act(() =>
      EventSourceDouble.instances[1].onmessage?.(
        new MessageEvent("message", {
          data: '{"sequence":2,"text":"fresh"}',
        }),
      ),
    );
    expect(result.current.lastMessage).toEqual({ sequence: 2, text: "fresh" });
  });

  it("remints after a remote WebSocket close until the caller closes", async () => {
    vi.useFakeTimers();
    mocks.post
      .mockResolvedValueOnce({
        data: {
          ticket: "socket-one",
          expires_in: 30,
          channel: "personal.updates",
          transport: "websocket",
        },
      })
      .mockResolvedValueOnce({
        data: {
          ticket: "socket-two",
          expires_in: 30,
          channel: "personal.updates",
          transport: "websocket",
        },
      });
    vi.stubGlobal("WebSocket", WebSocketDouble);

    const { result } = renderHook(() =>
      useRealtimeChannel({
        channel: "personal.updates",
        transport: "websocket",
        validate: isNotice,
      }),
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(WebSocketDouble.instances).toHaveLength(1);

    act(() =>
      WebSocketDouble.instances[0].onclose?.(
        new CloseEvent("close", { code: 1000 }),
      ),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
    });
    expect(mocks.post).toHaveBeenCalledTimes(2);
    expect(WebSocketDouble.instances).toHaveLength(2);

    act(() => result.current.close());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(result.current.status).toBe("closed");
    expect(mocks.post).toHaveBeenCalledTimes(2);
  });
});
