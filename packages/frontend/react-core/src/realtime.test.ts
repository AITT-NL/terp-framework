import { describe, expect, it } from "vitest";

import { parseMessage, transportUrl, useRealtimeChannel } from "./realtime";

interface Notice {
  sequence: number;
  text: string;
}

const isNotice = (value: unknown): value is Notice => {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return typeof record.sequence === "number" && typeof record.text === "string";
};

describe("realtime transport contract", () => {
  it("derives SSE and WebSocket URLs from the provider base URL with an opaque ticket", () => {
    expect(
      transportUrl("https://api.example.test/base", "sse", "notes.changed", "ticket value"),
    ).toBe(
      "https://api.example.test/api/v1/realtime/sse/notes.changed?ticket=ticket+value",
    );
    expect(
      transportUrl("https://api.example.test", "websocket", "notes/live", "opaque"),
    ).toBe(
      "wss://api.example.test/api/v1/realtime/ws/notes%2Flive?ticket=opaque",
    );
  });

  it("parses only JSON that passes the channel's runtime type guard", () => {
    expect(parseMessage('{"sequence":1,"text":"hello"}', isNotice)).toEqual({
      sequence: 1,
      text: "hello",
    });
    expect(() => parseMessage("not json", isNotice)).toThrow(/invalid JSON/);
    expect(() => parseMessage('{"sequence":"one"}', isNotice)).toThrow(
      /outside its declared type/,
    );
  });

  it("exports the sanctioned hook", () => {
    expect(typeof useRealtimeChannel).toBe("function");
  });
});
