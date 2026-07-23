import type { Action } from "@terpjs/contract";
import type { ReactNode } from "react";

import { useAuth } from "./TerpProvider";

/** Whether the current user may perform `action` (the UI gate; the backend re-checks). */
export function useCan(action: Action): boolean {
  return useAuth().can(action);
}

export interface AuthorizedProps {
  action: Action;
  children: ReactNode;
  /** Rendered when the user may not perform `action` (default: nothing). */
  fallback?: ReactNode;
}

/** Render `children` only when the current user may perform `action`, else `fallback`. */
export function Authorized({ action, children, fallback = null }: AuthorizedProps) {
  return <>{useCan(action) ? children : fallback}</>;
}
