import { describe, expect, it } from "vitest";

import { ApiError, unwrap, unwrapOptional } from "./unwrap";

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

describe("unwrapOptional", () => {
  it("returns the data on a 2xx result, like unwrap", () => {
    expect(unwrapOptional({ data: { id: "s1" }, response: response(200) })).toEqual({
      id: "s1",
    });
  });

  it("returns null on a 404 — absence is a normal state, not a failure", () => {
    expect(
      unwrapOptional({
        error: { code: "not_found", detail: "No snapshot published yet." },
        response: response(404),
      }),
    ).toBeNull();
  });

  it("throws the same ApiError as unwrap for every other failure", () => {
    let caught: unknown;
    try {
      unwrapOptional({
        error: { code: "permission_denied", detail: "You do not have permission." },
        response: response(403),
      });
    } catch (error) {
      caught = error;
    }
    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(403);
  });
});

// The per-field half of the error envelope.
//
// `Field` shipped an `error` prop, a `field-error` marker, an `aria-describedby`, an
// `aria-invalid` and a style rule for all of it, and nothing in this package could produce the
// value: every `error=` on a `Field` in all three trees was a test or a specimen. The reason was
// one function here, which computed each reason's field path and then joined it into a sentence.
// The information reached the client and was discarded on arrival.
//
// So these do not assert that a parser parses. Each one names a way the path can be lost again.
describe("ApiError.fields", () => {
  function failureOf(error: unknown, status = 422): ApiError {
    try {
      unwrap({ error, response: response(status) });
    } catch (thrown) {
      return thrown as ApiError;
    }
    throw new Error("unwrap returned instead of throwing");
  }

  it("keys a FastAPI 422 by dotted path, with the body/query/path prefix dropped", () => {
    expect(
      failureOf({
        detail: [
          { loc: ["body", "title"], msg: "String should have at least 1 character" },
          { loc: ["body", "owner", "email"], msg: "Input should be a valid email" },
        ],
      }).fields,
    ).toEqual({
      title: "String should have at least 1 character",
      "owner.email": "Input should be a valid email",
    });
  });

  it("reads the envelope's own `details`, whose `loc` is already a dotted string", () => {
    // `terp.core.ErrorDetail` documents its shape as "deliberately mirrors FastAPI's own 422
    // detail entries ... so a frontend handles both with one branch", and no such branch existed:
    // `unwrap` named `details` in a doc comment and never read the key. Handling only the array
    // spelling would have kept half of that promise while claiming all of it.
    // Mutation: delete the string arm of `fieldPath` and only this test goes red.
    expect(
      failureOf({
        code: "validation_failed",
        detail: "Two things are wrong.",
        details: [
          { code: "too_short", loc: "name", msg: "Name is too short." },
          { code: "not_unique", loc: "contact.email", msg: "Already registered." },
        ],
      }).fields,
    ).toEqual({ name: "Name is too short.", "contact.email": "Already registered." });
  });

  it("leaves the message to `detail` when `details` rides beside it", () => {
    // `details` is additive on the wire, so it must be additive here too. If it captured the
    // message slot that `detail` already fills, every existing caller's copy would change on the
    // day a backend first emits a reason list.
    expect(
      failureOf({
        detail: "Two things are wrong.",
        details: [{ code: "too_short", loc: "name", msg: "Name is too short." }],
      }).message,
    ).toBe("Two things are wrong.");
  });

  it("is empty for every failure that names no field", () => {
    expect(failureOf({ code: "permission_denied", detail: "Nope." }, 403).fields).toEqual({});
    expect(failureOf({ code: "conflict" }, 409).fields).toEqual({});
    expect(failureOf(undefined, 500).fields).toEqual({});
  });

  it("keeps a reason with no `loc` in the message, the only place it can go", () => {
    // A record keyed by field has no slot for a reason about the request as a whole, which
    // `ErrorDetail` documents as a supported case. Dropping it silently would be a regression
    // from the joined string this replaced, so the message keeps carrying it.
    const failure = failureOf({
      detail: [
        { loc: [], msg: "The window overlaps an existing one." },
        { loc: ["body", "name"], msg: "Name is too short." },
      ],
    });
    expect(failure.fields).toEqual({ name: "Name is too short." });
    expect(failure.message).toBe("The window overlaps an existing one.; name: Name is too short.");
  });

  it("takes the first reason per field and leaves the rest in the message", () => {
    const failure = failureOf({
      detail: [
        { loc: ["body", "password"], msg: "Too short." },
        { loc: ["body", "password"], msg: "Needs a digit." },
      ],
    });
    expect(failure.fields).toEqual({ password: "Too short." });
    expect(failure.message).toBe("password: Too short.; password: Needs a digit.");
  });

  it("is frozen, so one failure's reasons cannot be edited into something the server never said", () => {
    const fields = failureOf({ detail: [{ loc: ["body", "name"], msg: "Too short." }] }).fields;
    expect(() => {
      (fields as Record<string, string>).name = "anything";
    }).toThrow();
  });
});
