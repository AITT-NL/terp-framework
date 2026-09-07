import type { Action } from "@terpjs/contract";
import type { ReactNode } from "react";

import { useAuth } from "./TerpProvider";

/**
 * Whether the current user may perform `action` (the UI gate; the backend re-checks).
 *
 * Pass `module` on a module's own screen: a per-module rung the caller holds there raises the
 * answer exactly as it does at the guard (ADR 0121). Without it this compares the global rank
 * only, which is correct for a screen that belongs to no module and wrong for one that does —
 * it hid a module the caller could reach and rendered none of its controls.
 */
export function useCan(action: Action, module?: string): boolean {
  return useAuth().can(action, module);
}

/**
 * The caller's effective permission names, from `GET /me` (ADR 0096).
 *
 * `useCan` compares role *rank*, which is all the wire used to carry. A screen whose write
 * needs a **named** grant (`definitions.publish`) therefore had nothing to ask: it hid by
 * rank as a proxy and handled the 403 anyway — showing a button it knew might fail, or
 * hiding one the user was entitled to. This is the same set the server's guard enforces,
 * projected for display.
 *
 * Empty when signed out, and empty for an app that mounts no grant capability (it has no
 * named permissions). A *display* input only: the server re-checks every request, and a
 * client that treats this as authority has moved the gate to the wrong side of the wire.
 */
export function usePermissions(): readonly string[] {
  return useAuth().currentUser()?.permissions ?? [];
}

/** Whether the current user holds the named permission grant (the UI gate). */
export function useHasPermission(permission: string): boolean {
  return usePermissions().includes(permission);
}

export interface AuthorizedProps {
  action: Action;
  /** The module this action happens in, so a per-module rung can raise the answer. */
  module?: string;
  children: ReactNode;
  /**
   * Also require this named permission grant.
   *
   * Both must pass, which is deliberately what the server does: a `Policy` carrying a
   * `Permission` enforces the permission's role floor **and** the grant, so a UI that
   * checked only one would disagree with the endpoint in one direction or the other.
   */
  permission?: string;
  /** Rendered when the user may not perform `action` (default: nothing). */
  fallback?: ReactNode;
}

/** Render `children` only when the current user may perform `action`, else `fallback`. */
export function Authorized({
  action,
  module,
  permission,
  children,
  fallback = null,
}: AuthorizedProps) {
  const allowedByRank = useCan(action, module);
  const permissions = usePermissions();
  const allowed = allowedByRank && (permission === undefined || permissions.includes(permission));
  return <>{allowed ? children : fallback}</>;
}
