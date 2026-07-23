import { expect, test } from "@playwright/test";
import { EDITOR } from "@terpjs/conformance";

interface TicketResponse {
  ticket: string;
}

test("SSE and WebSocket redeem one-use tickets through the workbench proxy", async ({
  page,
}) => {
  await page.goto("/");
  const login = await page.request.post("/api/v1/auth/login", {
    data: EDITOR,
  });
  expect(login.status()).toBe(200);
  const { access_token: accessToken } = (await login.json()) as {
    access_token: string;
  };

  const mint = async (channel: string, transport: "sse" | "websocket") => {
    const response = await page.request.post("/api/v1/realtime/tickets", {
      headers: { Authorization: `Bearer ${accessToken}` },
      data: { channel, transport },
    });
    expect(response.status()).toBe(201);
    return (await response.json()) as TicketResponse;
  };

  const sseTicket = await mint("system.notices", "sse");
  const sseUrl = `/api/v1/realtime/sse/system.notices?ticket=${encodeURIComponent(sseTicket.ticket)}`;
  expect(
    await page.evaluate(
      (url) =>
        new Promise<string>((resolve) => {
          const source = new EventSource(url);
          const timer = window.setTimeout(() => {
            source.close();
            resolve("timeout");
          }, 20_000);
          source.onopen = () => {
            window.clearTimeout(timer);
            source.close();
            resolve("open");
          };
          source.onerror = () => {
            window.clearTimeout(timer);
            source.close();
            resolve("rejected");
          };
        }),
      sseUrl,
    ),
  ).toBe("open");
  expect(
    await page.evaluate(
      (url) =>
        new Promise<string>((resolve) => {
          const source = new EventSource(url);
          const timer = window.setTimeout(() => {
            source.close();
            resolve("timeout");
          }, 20_000);
          source.onopen = () => {
            window.clearTimeout(timer);
            source.close();
            resolve("unexpected-open");
          };
          source.onerror = () => {
            window.clearTimeout(timer);
            source.close();
            resolve("rejected");
          };
        }),
      sseUrl,
    ),
  ).toBe("rejected");

  const websocketTicket = await mint("personal.updates", "websocket");
  const websocketUrl = `/api/v1/realtime/ws/personal.updates?ticket=${encodeURIComponent(websocketTicket.ticket)}`;
  const messages = await page.evaluate(
      (path) =>
        new Promise<unknown[]>((resolve) => {
          const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
          const socket = new WebSocket(`${protocol}//${window.location.host}${path}`);
          const received: unknown[] = [];
          const timer = window.setTimeout(() => {
            socket.close();
            resolve([...received, { type: "timeout" }]);
          }, 10_000);
          socket.onopen = () => {
            socket.send(JSON.stringify({ action: "refresh" }));
            socket.send(JSON.stringify({ wrong: true }));
          };
          socket.onmessage = (event) => {
            received.push(JSON.parse(String(event.data)));
            if (received.length === 2) {
              window.clearTimeout(timer);
              socket.close(1000, "test complete");
              resolve(received);
            }
          };
          socket.onerror = () => {
            window.clearTimeout(timer);
            resolve([...received, { type: "error" }]);
          };
        }),
      websocketUrl,
    );
  expect(messages).toContainEqual({
    sequence: 1,
    text: "refresh accepted",
  });
  expect(messages).toContainEqual({ type: "error", code: "invalid_message" });

  expect(
    await page.evaluate(
      (path) =>
        new Promise<number>((resolve) => {
          const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
          const socket = new WebSocket(`${protocol}//${window.location.host}${path}`);
          const timer = window.setTimeout(() => {
            socket.close();
            resolve(0);
          }, 10_000);
          socket.onopen = () => resolve(1);
          socket.onerror = () => {};
          socket.onclose = () => {
            window.clearTimeout(timer);
            resolve(-1);
          };
        }),
      websocketUrl,
    ),
  ).toBe(-1);
});
