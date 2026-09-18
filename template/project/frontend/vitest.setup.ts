import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Testing Library does not unmount between tests on its own outside its own runner
// integration. Without this, a second test in a file queries a document still holding
// the first test's tree and matches the wrong element -- which shows up as a test that
// passes alone and fails in the file, the least useful failure there is.
afterEach(() => {
  cleanup();
});

// WAIT ON THE THING THAT GATES THE CLICK, NOT ON THE PAGE.
//
// The failure this note exists for costs a day the first time and is invisible in the
// diff: a test awaits the page heading, then clicks a control the component disables while
// an ambient load is in flight -- a submit button gated on `loading`, a menu item whose
// label comes from a fetched list, a row action that needs a permission set. jsdom raises
// NO event at all for a click on a disabled control, so nothing happens; the test then
// fails several lines later on whatever was waiting for the result, with a message naming
// that element instead. It looks like a slow machine, so the reflex is to raise the async
// budget or serialise the files, and neither helps: the click was lost, not late.
//
// The heading is up before the data is, so awaiting it proves nothing about readiness. Wait
// on the condition that actually gates the interaction:
//
//   const save = await screen.findByRole("button", { name: "Save" });
//   await waitFor(() => expect(save).toBeEnabled());
//   fireEvent.click(save);
//
// -- or on a piece of the loaded data itself (`await screen.findByRole("option", { name:
// "approver" })`). Either is deterministic; the heading is a proxy that happens to be true
// most of the time, which is the worst kind of wait.
