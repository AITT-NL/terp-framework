import type { Client } from "openapi-fetch";
import { describe, expect, it } from "vitest";

import { useTerpClient } from "./TerpProvider";

// A synthetic app contract with an endpoint that is NOT in @terp/contract's base profile —
// what an app's own openapi-typescript output looks like.
interface AppPaths {
  "/api/v1/invoices/": {
    get: {
      responses: {
        200: { content: { "application/json": { items: { id: string }[] } } };
      };
    };
  };
}

// Compile-time proofs, verified by `tsc --noEmit` (the typecheck CI step); never invoked at
// runtime, so the hook is not called outside a provider. They fail to compile if the hook
// stops threading the app's own paths through.
function _returnsAClientForTheAppsPaths(): Client<AppPaths> {
  return useTerpClient<AppPaths>();
}

function _typesTheAppsOwnEndpoint(client: Client<AppPaths>): unknown {
  return client.GET("/api/v1/invoices/", {});
}

describe("useTerpClient", () => {
  it("is generic over the app's own generated paths (typed at compile time)", () => {
    expect(typeof useTerpClient).toBe("function");
    expect(typeof _returnsAClientForTheAppsPaths).toBe("function");
    expect(typeof _typesTheAppsOwnEndpoint).toBe("function");
  });
});
