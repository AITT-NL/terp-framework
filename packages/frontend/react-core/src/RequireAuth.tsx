import type { ReactNode } from "react";

import { ErrorState } from "./ErrorState";
import { useAuth } from "./TerpProvider";
import { useStrings } from "./uiText";

export interface RequireAuthProps {
  /** Rendered while no user is signed in (e.g. a login view). */
  fallback: ReactNode;
  /** Rendered while the provider is checking a persisted session (default: nothing). */
  pending?: ReactNode;
  /**
   * Rendered when the boot session check got no answer at all — the backend did not
   * respond, or the connection failed. Defaults to a stated failure, never to the
   * login view: offering a sign-in form that cannot possibly succeed sends the reader
   * to check their password for a problem that is not theirs.
   */
  unreachable?: ReactNode;
  children: ReactNode;
}

/**
 * Render `children` only when a user is signed in, otherwise `fallback` (typically a login
 * view). Pair with the router so the authenticated app mounts only once there is a session;
 * the backend still enforces authorization on every request.
 *
 * Three states, not two. "Nobody is signed in" and "the server never answered" used to
 * be the same branch, and because a fetch to a dead proxy target hangs instead of
 * failing, the second one rendered `pending` — nothing — for as long as the page was
 * open. A blank screen with an empty console is the least diagnosable failure the stack
 * can produce, so it now says what happened.
 */
export function RequireAuth({
  fallback,
  pending = null,
  unreachable,
  children,
}: RequireAuthProps) {
  const auth = useAuth();
  const strings = useStrings();
  if (auth.loading()) return <>{pending}</>;
  if (auth.unreachable()) {
    return (
      <>
        {unreachable ?? (
          <ErrorState
            title={strings.backendUnreachableTitle}
            description={strings.backendUnreachableDescription}
          />
        )}
      </>
    );
  }
  return <>{auth.currentUser() !== null ? children : fallback}</>;
}
