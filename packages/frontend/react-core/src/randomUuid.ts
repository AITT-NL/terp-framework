/**
 * Generating a UUID, once, for everyone.
 *
 * `crypto.randomUUID` is not the API it looks like. `lib.dom` declares it
 * unconditionally on `Crypto`, and it exists only in a **secure context** — so on a
 * plain-http origin that is not localhost, `crypto.randomUUID()` is a call on
 * `undefined`. That throws a **synchronous** `TypeError`, TypeScript reports nothing
 * because as far as its type says the method is there, and a test suite running on
 * localhost never sees it either: localhost *is* a secure context, so the whole class is
 * invisible to the type checker, to review, and to CI at once.
 *
 * Same shape as the clipboard seam, and the same argument (ADR 0096 §3): a browser API
 * with a footgun, wrapped once. What makes it worth a seam rather than a lesson is that
 * the platform routes you here — the idempotency capability's contract is a
 * **client-generated** `Idempotency-Key` header, so an app wiring retry-safety reaches
 * for exactly this method — and the topology it breaks in is the one Terp itself ships:
 * the compose files publish plain http, so any deployment reached by hostname rather than
 * localhost is an insecure context.
 *
 * **The fallback never weakens the value.** `crypto.getRandomValues` is *not*
 * secure-context-gated and is available wherever `crypto` is, so an insecure context
 * still gets a cryptographically random v4 — assembled here rather than by the missing
 * method. There is deliberately no `Math.random` path: a UUID standing in for an
 * idempotency key or an optimistic row id is a value collisions corrupt, and silently
 * degrading its entropy to keep a call site quiet is the kind of "it worked" the clipboard
 * seam exists to refuse. With no `crypto` at all this throws, because there is nothing
 * honest left to return.
 */

/** Two hex digits per byte, precomputed: the formatting is 16 lookups, not 16 `padStart`s. */
const HEX_BYTE = Array.from({ length: 256 }, (_, byte) => (byte + 0x100).toString(16).slice(1));

/**
 * No source of cryptographic randomness is reachable, so no UUID can be produced.
 *
 * Thrown rather than papered over with `Math.random`: see the module docstring. In a
 * browser this means `crypto` itself is missing, which is a far older environment than the
 * insecure-context case this module exists for — that one is handled and never reaches
 * here.
 */
export class RandomUuidUnavailableError extends Error {
  constructor() {
    super(
      "No cryptographic randomness is available: neither crypto.randomUUID nor " +
        "crypto.getRandomValues could be reached. A UUID is not generated from a weaker " +
        "source, because the values it stands in for are ones a collision corrupts.",
    );
    this.name = "RandomUuidUnavailableError";
  }
}

/**
 * A cryptographically random v4 UUID, in every context — secure or not.
 *
 * Use it instead of `crypto.randomUUID()`:
 *
 * ```ts
 * const key = randomUuid();
 * await unwrap(client.POST("/api/v1/invoices/", { body, headers: { "Idempotency-Key": key } }));
 * ```
 *
 * Uses `crypto.randomUUID` where it exists and assembles the same thing from
 * `crypto.getRandomValues` where it does not, so the entropy is identical either way and
 * only the assembly moves. Throws {@link RandomUuidUnavailableError} when neither is
 * reachable.
 */
export function randomUuid(): string {
  // Read through globalThis: `crypto` as a bare global is a ReferenceError where it is
  // absent, and the point of this function is to answer that question rather than raise it.
  const source: Crypto | undefined = globalThis.crypto;
  if (source === undefined) {
    throw new RandomUuidUnavailableError();
  }
  if (typeof source.randomUUID === "function") {
    return source.randomUUID();
  }
  if (typeof source.getRandomValues !== "function") {
    throw new RandomUuidUnavailableError();
  }

  const bytes = source.getRandomValues(new Uint8Array(16));
  // The two fields RFC 9562 fixes: version 4 in the high nibble of octet 6, and the
  // variant's `10` in the top bits of octet 8. Without these the value is 128 random bits
  // that merely look like a UUID, and anything parsing its version reads a nonsense one.
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;

  const hex = (index: number): string => HEX_BYTE[bytes[index]];
  return (
    hex(0) +
    hex(1) +
    hex(2) +
    hex(3) +
    "-" +
    hex(4) +
    hex(5) +
    "-" +
    hex(6) +
    hex(7) +
    "-" +
    hex(8) +
    hex(9) +
    "-" +
    hex(10) +
    hex(11) +
    hex(12) +
    hex(13) +
    hex(14) +
    hex(15)
  );
}
