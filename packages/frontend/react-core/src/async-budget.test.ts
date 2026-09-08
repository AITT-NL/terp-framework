import fs from "node:fs";
import path from "node:path";

import { getConfig } from "@testing-library/dom";
import { expect, it } from "vitest";

// Testing Library's 1000ms default is not enough for this suite, and the way it fails is
// the problem: intermittently, on whichever test the machine happened to be busy during.
// Five times in one day, four different tests, each passing alone and on a re-run — and
// one of them red in CI on a branch whose own change was fine, which is a day spent
// reading a diff that was never the cause.
//
// The budget is configured in vitest.setup.ts. A number in a setup file is exactly the
// kind of thing a later edit lowers back to the default while chasing a slow suite, and
// nothing would say so until the flakes returned, so it is asserted here.

const _MINIMUM_ASYNC_BUDGET_MS = 2_000;

function _source(...segments: string[]): string {
  return fs.readFileSync(path.join(import.meta.dirname, ...segments), "utf8");
}

it("waits long enough for a mocked fetch, its state update and the re-render", () => {
  // Not a render: `findBy*` in these tests spans a resolved fetch, the state it sets and
  // the re-render that puts the text on screen. One second covers that on an idle machine.
  expect(getConfig().asyncUtilTimeout).toBeGreaterThanOrEqual(_MINIMUM_ASYNC_BUDGET_MS);
});

it("stays under a toast's life, so a wait cannot outlive what the next line asserts", () => {
  // The ceiling, and it is not theoretical: raising the budget TO the toast duration is
  // what the first version of this change did, and it broke the admin test that waits for
  // a field error and then reads the toast synchronously. A wait that resolves late enough
  // leaves nothing to read, and the failure looks like a product bug rather than a config
  // one. The number lives in toast.tsx and is module-private, so it is read from source:
  // a lower duration there must fail here rather than start dismissing toasts mid-test.
  const declared = _source("toast.tsx").match(/DEFAULT_DURATION_MS\s*=\s*([\d_]+)/);

  expect(declared, "toast.tsx declares no DEFAULT_DURATION_MS").not.toBeNull();
  const toastDurationMs = Number(declared![1].replaceAll("_", ""));

  expect(getConfig().asyncUtilTimeout).toBeLessThan(toastDurationMs);
});

it("lets the matcher lose before the test does, so the failure names the element", () => {
  // Ordering, not size. If `testTimeout` were the smaller of the two, a genuinely failing
  // assertion would be cut off mid-wait and reported as "test timed out" — which says
  // nothing about what was being waited for. The matcher must run out first so its own
  // "Unable to find an element with the text ..." is what a reader gets.
  const declared = _source("..", "vite.config.ts").match(/testTimeout:\s*([\d_]+)/);

  expect(declared, "vite.config.ts declares no testTimeout").not.toBeNull();
  const testTimeout = Number(declared![1].replaceAll("_", ""));

  expect(testTimeout).toBeGreaterThan(getConfig().asyncUtilTimeout);
});
