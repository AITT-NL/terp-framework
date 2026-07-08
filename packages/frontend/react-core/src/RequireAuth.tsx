import type { ReactNode } from "react";

import { useAuth } from "./TerpProvider";

export interface RequireAuthProps {
  /** Rendered while no user is signed in (e.g. a login view). */
  fallback: ReactNode;
  /** Rendered while the provider is checking a persisted session (default: nothing). */
  pending?: ReactNode;
  children: ReactNode;
}

/**
 * Render `children` only when a user is signed in, otherwise `fallback` (typically a login
 * view). Pair with the router so the authenticated app mounts only once there is a session;
 * the backend still enforces authorization on every request.
 */
export function RequireAuth({ fallback, pending = null, children }: RequireAuthProps) {
  const auth = useAuth();
  if (auth.loading()) return <>{pending}</>;
  return <>{auth.currentUser() !== null ? children : fallback}</>;
}
