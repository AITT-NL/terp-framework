import { afterEach, describe, expect, it, vi } from "vitest";

import { randomUuid, RandomUuidUnavailableError } from "./randomUuid";

const V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

/** Swap the ambient `crypto` for the duration of a case. */
function withCrypto(replacement: unknown): void {
  vi.stubGlobal("crypto", replacement);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("randomUuid", () => {
  it("uses the native generator where the context is secure", () => {
    const randomUUID = vi.fn(() => "11111111-2222-4333-8444-555555555555");
    withCrypto({ randomUUID, getRandomValues: vi.fn() });
    expect(randomUuid()).toBe("11111111-2222-4333-8444-555555555555");
    expect(randomUUID).toHaveBeenCalledOnce();
  });

  it("produces a well-formed v4 with randomUUID absent, as on an http origin", () => {
    // The case the whole module exists for. crypto.randomUUID is secure-context-only and
    // lib.dom declares it unconditionally, so this shape type-checks and throws a
    // synchronous TypeError in a browser -- and never on localhost, so no test sees it.
    const real = globalThis.crypto;
    withCrypto({ getRandomValues: real.getRandomValues.bind(real) });
    for (let i = 0; i < 50; i += 1) {
      expect(randomUuid()).toMatch(V4);
    }
  });

  it("pins the version and variant bits rather than emitting 128 loose bits", () => {
    // Without the two masks the value merely looks like a UUID, and anything reading its
    // version field gets a nonsense answer. Feed all-zero and all-one bytes: the only
    // digits that must not follow the input are those two.
    for (const fill of [0x00, 0xff]) {
      withCrypto({
        getRandomValues: (array: Uint8Array) => {
          array.fill(fill);
          return array;
        },
      });
      const value = randomUuid();
      expect(value).toMatch(V4);
      expect(value[14], "the version nibble is always 4").toBe("4");
      expect("89ab", "the variant nibble is 8, 9, a or b").toContain(value[19]);
    }
  });

  it("does not repeat itself", () => {
    const real = globalThis.crypto;
    withCrypto({ getRandomValues: real.getRandomValues.bind(real) });
    const seen = new Set(Array.from({ length: 500 }, () => randomUuid()));
    expect(seen.size).toBe(500);
  });

  it("refuses rather than falling back to a weaker source", () => {
    // No Math.random path, deliberately: a UUID standing in for an idempotency key is a
    // value a collision corrupts, so quietly degrading its entropy to keep the call site
    // quiet is the "it worked" this seam exists to refuse.
    withCrypto(undefined);
    expect(() => randomUuid()).toThrow(RandomUuidUnavailableError);

    withCrypto({});
    expect(() => randomUuid()).toThrow(RandomUuidUnavailableError);

    withCrypto({ randomUUID: "not a function", getRandomValues: undefined });
    expect(() => randomUuid()).toThrow(RandomUuidUnavailableError);
  });

  it("says why it refused", () => {
    withCrypto(undefined);
    expect(() => randomUuid()).toThrow(/crypto.randomUUID nor crypto.getRandomValues/);
  });
});
