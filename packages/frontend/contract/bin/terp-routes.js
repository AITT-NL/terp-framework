#!/usr/bin/env node
/**
 * The `terp-routes` executable (ADR 0092) — a real entry point, deliberately.
 *
 * This file exists instead of an `import.meta.url === process.argv[1]` guard inside the
 * module: npm installs a bin as a shim/symlink, so the module's own URL and argv[1] do
 * NOT match when it is invoked as `terp-routes`, and such a guard silently skips the
 * whole program while still exiting 0. That failure is invisible in the worst possible
 * way — a drift check that passes because it never ran.
 */
import { run } from "../src/routes-codegen.js";

try {
  process.exit(run(process.argv.slice(2)));
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(2);
}
