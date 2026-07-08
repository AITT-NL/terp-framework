import { describe, expect, it } from "vitest";

import { ApiError, unwrap } from "./unwrap";

function response(status: number): Response {
  return new Response(null, { status });
}

describe("unwrap", () => {
  it("returns the data on a 2xx result", () => {
    expect(unwrap({ data: { items: [1, 2] }, response: response(200) })).toEqual({
      items: [1, 2],
    });
  });

  it("returns undefined data on a 204 (no body) without throwing", () => {
    expect(unwrap<undefined>({ response: response(204) })).toBeUndefined();
  });

  it("throws the backend error `detail` on an HTTP error", () => {
    expect(() =>
      unwrap({
        error: { code: "permission_denied", detail: "You do not have permission." },
        response: response(403),
      }),
    ).toThrow("You do not have permission.");
  });

  it("flattens structured validation detail into field messages", () => {
    expect(() =>
      unwrap({
        error: {
          detail: [
            { loc: ["body", "title"], msg: "String should have at least 1 character" },
            { loc: ["body", "owner", "email"], msg: "Input should be a valid email" },
          ],
        },
        response: response(422),
      }),
    ).toThrow("title: String should have at least 1 character; owner.email: Input should be a valid email");
  });

  it("falls back to the error `code`, then the status, when there is no detail", () => {
    expect(() => unwrap({ error: { code: "conflict" }, response: response(409) })).toThrow(
      "conflict",
    );
    expect(() => unwrap({ response: response(500) })).toThrow("HTTP 500");
  });

  it("throws an ApiError carrying the stable code, status, and request id", () => {
    let caught: unknown;
    try {
      unwrap({
        error: { code: "stale_data", detail: "Row changed.", request_id: "req-1" },
        response: response(409),
      });
    } catch (error) {
      caught = error;
    }
    expect(caught).toBeInstanceOf(ApiError);
    const apiError = caught as ApiError;
    expect(apiError.code).toBe("stale_data");
    expect(apiError.status).toBe(409);
    expect(apiError.requestId).toBe("req-1");
    expect(apiError.message).toBe("Row changed.");
  });
});
