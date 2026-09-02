import { useEffect, useState } from "react";

import { useTerpClient } from "../TerpProvider";
import { unwrap } from "../unwrap";
import type { TerpStrings } from "../uiText";

/** One rung of the app's declared ladder, ready to render. */
export interface AdminRoleOption {
  rank: number;
  /** The name the app declared — `viewer`, `approver`, whatever it chose. */
  name: string;
  /** What to show a person: a framework translation where one exists, else the name. */
  label: string;
}

/**
 * The three rungs `terp-core` ships, by rank. Used only to *translate* a declared rung whose
 * name matches one of them — never to decide which rungs exist. That distinction is the whole
 * point of this file: `roles.ts` used to return these three ranks as literals, so an app with a
 * four-rung ladder got a three-rung admin UI while ADR 0022 promised the role model was the
 * app's. Now the ladder comes from `GET /api/v1/access/model` and this map only supplies copy.
 */
function packagedLabel(strings: TerpStrings, name: string): string | null {
  if (name === "viewer") return strings.roleViewer;
  if (name === "editor") return strings.roleEditor;
  if (name === "admin") return strings.roleAdmin;
  return null;
}

export interface AccessLadder {
  /** The declared rungs, rank-ascending. Empty until the first load resolves. */
  rungs: AdminRoleOption[];
  /** True while the model is in flight. */
  loading: boolean;
  /** The last failure message, or `null`. */
  error: string | null;
}

/**
 * The app's declared role ladder, read from the access model.
 *
 * Admin-only, like the endpoint — every screen that needs a ladder is already behind the
 * `role: "admin"` route guard, so there is no case where this is fetched by a caller the
 * server would refuse.
 *
 * A rung the framework has no translation for renders under its declared name rather than as
 * `rank 25`, which is what the old rank-only fallback produced. The name is the app author's
 * own word for it, so it is a better answer than a number even before anyone translates it.
 */
export function useAccessLadder(strings: TerpStrings): AccessLadder {
  const client = useTerpClient();
  const [rungs, setRungs] = useState<AdminRoleOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setLoading(true);
    // `unwrap` is how every hook in here reads a typed response: it throws the `ApiError`
    // whose stable `code` the error-message machinery maps to copy, rather than leaving each
    // caller to branch on `data` versus `error`.
    void (async () => {
      try {
        const model = unwrap(await client.GET("/api/v1/access/model", {}));
        if (!live) return;
        setRungs(
          [...model.roles]
            .sort((a, b) => a.rank - b.rank)
            .map((role) => ({
              rank: role.rank,
              name: role.name,
              label: packagedLabel(strings, role.name) ?? role.name,
            })),
        );
        setError(null);
      } catch (cause: unknown) {
        if (live) setError(cause instanceof Error ? cause.message : String(cause));
      } finally {
        if (live) setLoading(false);
      }
    })();
    return () => {
      live = false;
    };
  }, [client, strings]);

  return { rungs, loading, error };
}
