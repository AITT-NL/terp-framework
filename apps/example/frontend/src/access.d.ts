// The app's access vocabulary, handed to the framework's manifest types.
//
// `terp openapi` emits this app's permission and role names as enums, and
// `npm run generate` turns them into string-literal unions in `api/schema.d.ts`.
// These six lines make `@terpjs/contract` use them, so a route, a nav entry or a
// `useHasPermission` call naming a permission this app does not declare stops
// type-checking instead of failing at runtime — over-gating (a screen 403s for
// someone who may use it) or under-gating (a link renders and every request behind
// it fails), neither of which anything but an end-to-end test would catch.
//
// It names TYPES, not values, so it cannot drift: regenerate the client and every
// stale spelling in the app goes red at once.
import type { components } from "./api/schema";

declare module "@terpjs/contract" {
  interface TerpAccessVocabulary {
    permission: components["schemas"]["TerpPermission"];
    role: components["schemas"]["TerpRole"];
  }
}
