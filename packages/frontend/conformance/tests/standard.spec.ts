import { expect, test, type APIRequestContext } from "@playwright/test";

import { ADMIN } from "../src/index";

// Terp Standard black-box probes (spec/catalog entries with layer "black-box"): these
// invariants are observable on a RUNNING app with no source access, so they are portable to
// any stack — this file is the reference realisation the catalog's `black-box` enforcement
// entries point at. Like auth.spec.ts, the probes use only the base profile (auth + the
// seeded admin) plus the `users` capability every generated app starts with, so they stay
// app-agnostic. Each test title is the catalog entry's enforcement `ref`.

async function bearer(request: APIRequestContext): Promise<{ Authorization: string }> {
  const response = await request.post("/api/v1/auth/login", { data: ADMIN });
  expect(response.ok()).toBe(true);
  const { access_token } = (await response.json()) as { access_token: string };
  return { Authorization: "Bearer " + access_token };
}

// spec/catalog/backend/list_routes_paginate.json
test("standard: list routes return a capped Page envelope", async ({ request }) => {
  const headers = await bearer(request);

  // A collection GET is a uniform Page envelope, never a bare JSON array.
  const page = await request.get("/api/v1/users/", { headers });
  expect(page.ok()).toBe(true);
  const body = (await page.json()) as Record<string, unknown>;
  expect(Array.isArray(body)).toBe(false);
  expect(body).toMatchObject({ items: expect.any(Array), total: expect.any(Number) });
  expect(typeof body.limit).toBe("number");
  expect(typeof body.skip).toBe("number");

  // The page size is capped fail-closed: an oversized limit is refused, not honoured.
  const oversized = await request.get("/api/v1/users/?limit=100000", { headers });
  expect(oversized.status()).toBe(422);
});

// spec/catalog/backend/safe_methods_are_read_only.json
test("standard: safe methods observably mutate nothing", async ({ request }) => {
  const headers = await bearer(request);

  // Reading a collection is repeatable: the GETs themselves change no state, so the
  // second read reports exactly the population the first one saw.
  const first = await request.get("/api/v1/users/", { headers });
  expect(first.ok()).toBe(true);
  const before = (await first.json()) as { total: number; items: unknown[] };

  const second = await request.get("/api/v1/users/", { headers });
  expect(second.ok()).toBe(true);
  const after = (await second.json()) as { total: number; items: unknown[] };

  expect(after.total).toBe(before.total);
  expect(after.items.length).toBe(before.items.length);
});

// spec/catalog/backend/schemas_exclude_sensitive_fields.json
const SENSITIVE_KEY = new RegExp(
  "(?:^|_)(?:password|passwd|pwd|passphrase|secret|salt|api_key|apikey" +
    "|private_key|privatekey|credentials?)(?:$|_)|(?:^|_)token$",
);
const SENSITIVE_KEY_EXCLUSIONS = new Set(["token_version", "version"]);

function sensitiveKeys(value: unknown, found: string[] = []): string[] {
  if (Array.isArray(value)) {
    value.forEach((item) => sensitiveKeys(item, found));
  } else if (value !== null && typeof value === "object") {
    for (const [key, nested] of Object.entries(value)) {
      if (!SENSITIVE_KEY_EXCLUSIONS.has(key.toLowerCase()) && SENSITIVE_KEY.test(key.toLowerCase())) {
        found.push(key);
      }
      sensitiveKeys(nested, found);
    }
  }
  return found;
}

test("standard: responses never expose credential-shaped fields", async ({ request }) => {
  const headers = await bearer(request);
  for (const path of ["/api/v1/users/", "/api/v1/me/"]) {
    const response = await request.get(path, { headers });
    expect(response.ok()).toBe(true);
    expect(sensitiveKeys(await response.json()), `${path} leaked a credential-shaped field`).toEqual(
      [],
    );
  }
});
