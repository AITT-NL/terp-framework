import { describe, expect, it } from "vitest";

import { routeFieldErrors } from "./fieldErrors";
import { ApiError } from "./unwrap";

function failure(fields: Record<string, string>): ApiError {
  return new ApiError("Kan niet opslaan.", { status: 422, code: "validation_failed", fields });
}

describe("routeFieldErrors", () => {
  it("hands back the reasons this form actually renders", () => {
    const { shown, leftover } = routeFieldErrors(
      failure({ name: "Naam is verplicht.", description: "Te lang." }),
      ["name", "description"],
    );
    expect(shown).toEqual({ name: "Naam is verplicht.", description: "Te lang." });
    expect(leftover).toBe(false);
  });

  it("reports a reason naming a field the form has no input for", () => {
    // The whole point of the second return value. Without it a caller writes "if there
    // are fields, set them and return", and a reason it cannot show sets state nobody
    // reads AND suppresses the toast — the user presses Save and nothing happens at all.
    const { shown, leftover } = routeFieldErrors(
      failure({ name: "Naam is verplicht.", tenant_id: "Onbekende organisatie." }),
      ["name"],
    );
    expect(shown).toEqual({ name: "Naam is verplicht." });
    expect(leftover).toBe(true);
  });

  it("reports leftover even when it can show nothing at all", () => {
    // The worst case for the naive version: every reason is unshowable, so `shown` is
    // empty and a caller keying off "did we set any fields" falls through correctly only
    // because `leftover` said so.
    const { shown, leftover } = routeFieldErrors(failure({ tenant_id: "Onbekend." }), ["name"]);
    expect(shown).toEqual({});
    expect(leftover).toBe(true);
  });

  it("treats a failure that names no field as nothing to route", () => {
    const { shown, leftover } = routeFieldErrors(failure({}), ["name"]);
    expect(shown).toEqual({});
    expect(leftover).toBe(false);
  });

  it("is inert for anything that is not an ApiError", () => {
    // A thrown string, a TypeError from the caller's own code: there is nothing to read,
    // and guessing would put a message under a field the server never mentioned.
    for (const thrown of [new Error("boom"), "boom", null, undefined]) {
      expect(routeFieldErrors(thrown, ["name"])).toEqual({ shown: {}, leftover: false });
    }
  });
});
