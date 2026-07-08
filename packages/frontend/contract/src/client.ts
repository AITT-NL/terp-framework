import createClient, { type Client, type ClientOptions } from "openapi-fetch";

import type { paths } from "./schema";

/**
 * Build a fully typed Terp API client from the backend OpenAPI contract.
 *
 * Every path, method, path/query parameter, request body and response is type-checked
 * against `openapi.json` (regenerated into `./schema`), so a call that does not match
 * the backend fails to compile — the frontend client cannot drift from the API.
 *
 * @example
 * const api = createTerpClient({ baseUrl: "https://api.example.com" });
 * const { data, error } = await api.GET("/api/v1/notes/", { params: { query: { skip: 0 } } });
 */
export function createTerpClient(options: ClientOptions) {
  return createClient<paths>(options);
}

export type TerpClient = ReturnType<typeof createTerpClient>;

/**
 * A typed Terp client for ANY app's generated `paths` (the openapi-typescript output of
 * that app's own OpenAPI document). `@terp/react-core`'s `useTerpClient<paths>()` returns
 * this, so a client app types calls to its OWN endpoints — not only the base-profile paths
 * bundled in this package. The runtime client is the same; only the compile-time view differs.
 */
export type TerpClientFor<AppPaths extends {}> = Client<AppPaths>;
