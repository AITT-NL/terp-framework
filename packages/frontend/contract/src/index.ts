// Public surface of @terpjs/contract — the generated, drift-checked API contract.
export { createTerpClient } from "./client";
export type { TerpClient, TerpClientFor } from "./client";
export type { components, operations, paths } from "./schema";

// Stack-agnostic UI contract: the module/route/nav manifest and the auth/session shape.
export { defineModuleManifest } from "./manifest";
export type { ModuleManifest, ModuleRoute, NavItem, RoleName } from "./manifest";
export type { AccessToken, Action, AuthSession, Credentials, CurrentUser } from "./auth";
