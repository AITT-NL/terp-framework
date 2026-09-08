import { getConfig } from "@testing-library/dom";
import { expect, it } from "vitest";

// Testing Library's 1000ms default is not enough for this suite, and the way it fails is
// the problem: intermittently, on whichever test the machine happened to be busy during.
// Five failures across one day, four different tests, each passing alone and on a re-run —
// and one of them red in CI on a branch whose own change was fine.
//
// What this file holds is that the `configure` call in vitest.setup.ts actually TOOK
// EFFECT. Reading the number back out of the setup file would pass with the call deleted
// and the constant left behind, which is the one failure mode a config guard must not
// have. The bounds it has to sit between — above the default, below a toast's
// auto-dismiss, below `testTimeout` — span three files, so they are held from the Python
// side in `test_frontend_async_budget.py`, the way this repository holds its other
// cross-file config invariants. This package compiles with `types: []`, and reading files
// here would need node types it deliberately does not have.

const _WELL_ABOVE_THE_DEFAULT_MS = 2_000;

it("configures an async budget the loaded machine can actually meet", () => {
  // Not a render: `findBy*` in these tests spans a resolved fetch, the state it sets and
  // the re-render that puts the text on screen. One second covers that only when idle.
  expect(getConfig().asyncUtilTimeout).toBeGreaterThanOrEqual(_WELL_ABOVE_THE_DEFAULT_MS);
});
