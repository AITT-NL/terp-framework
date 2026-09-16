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
