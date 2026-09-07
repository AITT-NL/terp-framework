import { useEffect, useState } from "react";
import type { components } from "@terpjs/contract";

import { Alert } from "../ui/Alert";
import { ConfirmDialog } from "../ConfirmDialog";
import { LoadingState } from "../LoadingState";
import { Stack } from "../layout";
import { TileGroup } from "../ui/TileGroup";
import { useTerpClient } from "../TerpProvider";
import { useStrings } from "../uiText";
import { useToast } from "../toast";
import { unwrap } from "../unwrap";

import { NO_ACCESS } from "./accessModel";
import type { ModuleRow } from "./accessModel";
import { tilesFor, topRung } from "./accessTiles";
import { useAccessLadder } from "./useAccessLadder";
import type { AdminRoleOption } from "./useAccessLadder";

type HeldModuleRole = components["schemas"]["HeldModuleRoleRead"];

/** What the panel is about to do, held while the confirmation is open. */
type Pending =
  | { kind: "assign"; module: string; label: string; role: string; rank: number }
  | { kind: "revoke"; module: string; label: string };

export interface ModuleAccessPanelProps {
  /** The subject the rungs are being set for — a user id or a group id. */
  subjectId: string;
  /**
   * The subject's rank everywhere, when it has one.
   *
   * A user does; a group does not, because ADR 0074 gives groups permissions rather than
   * roles. It is display-only: a rung at or below it changes nothing, since the guard resolves
   * a module rank as the *higher* of the two, and the strip says so instead of letting someone
   * assign `viewer` to an editor and wonder why nothing happened.
   */
  globalRank?: number | null;
}

/** A failure's own message where it has one, so a 400 from the writer names what it refused. */
function failure(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback;
}

/**
 * The rung this subject holds in *this* module by its own name, or `null`.
 *
 * One reader, because the strip and the commit handler both need it and both got it subtly
 * wrong when they each derived it: collapsing "no row" and "a row whose rank the app no longer
 * declares" into the same value made the stale row unclearable, since committing `no access`
 * then looked like committing what was already selected.
 *
 * A rung arriving through a group is excluded — that is a fact about the group, and the strip
 * can only change what this subject was given directly.
 */
function directRung(held: readonly HeldModuleRole[], module: string): HeldModuleRole | null {
  return held.find((entry) => entry.module === module && entry.via.kind === "self") ?? null;
}

/** The declared rung a rank sits at, for the floor marker: the highest rung the rank clears. */
function rungAtOrBelow(rungs: readonly AdminRoleOption[], rank: number | null): string | null {
  if (rank === null) return null;
  const cleared = rungs.filter((rung) => rung.rank <= rank);
  return cleared.length === 0 ? null : cleared[cleared.length - 1].name;
}

function ModuleStrip({
  row,
  held,
  floor,
  busy,
  onPick,
}: {
  row: ModuleRow;
  held: HeldModuleRole[];
  floor: string | null;
  busy: boolean;
  onPick: (row: ModuleRow, value: string) => void;
}) {
  const strings = useStrings();
  const direct = directRung(held, row.name);
  const inherited = held.filter(
    (entry) => entry.module === row.name && entry.via.kind !== "self",
  );

  return (
    <Stack gap={2}>
      <Stack direction="row" gap={2} align="center">
        <strong>{row.label}</strong>
        <code>{row.name}</code>
      </Stack>
      <TileGroup
        label={row.label}
        tiles={tilesFor(row, strings)}
        // Three states, not two. No row selects the real `no access` tile; a live rung selects
        // its own; and a rung whose rank the app no longer declares reports `role: null`, which
        // selects *nothing* — with the stale note below saying why. Collapsing that third state
        // into `no access` would claim the subject holds nothing while a row sits there doing
        // nothing, which is the one case where saying so is the whole point.
        value={direct === null ? NO_ACCESS : direct.role}
        floor={floor}
        disabled={busy}
        onCommit={(value) => onPick(row, value)}
      />
      {floor !== null && (
        <span data-terp="tile-note">
          {strings.moduleAccessFloor.replace("{role}", floor)}
        </span>
      )}
      {direct !== null && direct.stale.length > 0 && (
        <Alert tone="warning">
          {strings.moduleAccessStale.replace("{reason}", direct.stale.join("; "))}
        </Alert>
      )}
      {inherited.map((entry) => (
        <span key={`${entry.via.id}:${entry.role_rank}`} data-terp="tile-note">
          {/* Provenance, because "why can this person do that?" is the question an
              administrator has to be able to answer, and a strip that showed only the direct
              row would answer it wrongly on exactly the accounts where it matters. */}
          {strings.moduleAccessVia
            .replace("{role}", entry.role ?? String(entry.role_rank))
            .replace("{name}", entry.via.name ?? entry.via.id)}
        </span>
      ))}
    </Stack>
  );
}

/**
 * Set a subject's role inside one module — the write half of the permission surface.
 *
 * It lives on the subject's own detail screen rather than on `/admin/access`, because that is
 * the only place the choice has a subject (ADR 0121). The access screen explains what a rung
 * *means*; this decides who holds one, and the tiles it offers are built from the same
 * projection, so the explanation a reader saw there is the explanation they act on here.
 *
 * Only modules that opted in are listed. A module that refuses is not a gap the panel should
 * explain — `/admin/access` lists it with its reason — and offering a control the server would
 * refuse is worse than not offering one.
 *
 * Assigning the top rung is behind a confirmation, which is what makes the strip's manual
 * activation load-bearing: arrowing across the tiles must not fire it.
 */
export function ModuleAccessPanel({ subjectId, globalRank = null }: ModuleAccessPanelProps) {
  const client = useTerpClient();
  const strings = useStrings();
  const toast = useToast();
  const { rungs, modules, loading, error } = useAccessLadder(strings);
  const [held, setHeld] = useState<HeldModuleRole[]>([]);
  const [pending, setPending] = useState<Pending | null>(null);
  const [busy, setBusy] = useState(false);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const subject = unwrap(
          await client.GET("/api/v1/access/subjects/{subject_id}", {
            params: { path: { subject_id: subjectId } },
          }),
        );
        if (live) setHeld(subject.module_roles);
      } catch (cause: unknown) {
        if (live) toast.warning(failure(cause, strings.requestFailed));
      }
    })();
    return () => {
      live = false;
    };
    // A version counter rather than a callback the writer invokes, which is the idiom the group
    // screen already uses for the same job. The point is that *every* read happens inside this
    // effect, so every read is covered by the `live` guard — a writer that set the rows itself
    // could resolve after the screen was gone, or after a newer read had already landed.
    //
    // `toast` and `strings` are deliberately not dependencies: showing a message must not
    // re-fetch, and neither must a language change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, subjectId, version]);

  const assignable = modules.filter((row) => row.assignable);
  const floor = rungAtOrBelow(rungs, globalRank);

  function onPick(row: ModuleRow, value: string) {
    const entry = directRung(held, row.name);
    const current = entry === null ? NO_ACCESS : entry.role;
    // Committing the tile that is already selected is not a change, and a request that stores
    // what is already stored would still write an audit row saying someone changed something.
    // A stale row's `current` is `null`, which is not any tile's value — so `no access` is a
    // real change there, which is what makes such a row clearable at all.
    if (value === current) return;
    if (value === NO_ACCESS) {
      setPending({ kind: "revoke", module: row.name, label: row.label });
      return;
    }
    const rung = rungs.find((option) => option.name === value);
    if (rung === undefined) return;
    if (value === topRung(row)) {
      setPending({
        kind: "assign",
        module: row.name,
        label: row.label,
        role: value,
        rank: rung.rank,
      });
      return;
    }
    void write(row.name, rung.rank);
  }

  async function write(module: string, rank: number | null) {
    setBusy(true);
    try {
      if (rank === null) {
        unwrap(
          await client.DELETE("/api/v1/access/subjects/{subject_id}/module-roles/{module}", {
            params: { path: { subject_id: subjectId, module } },
          }),
        );
      } else {
        unwrap(
          await client.PUT("/api/v1/access/subjects/{subject_id}/module-roles/{module}", {
            params: { path: { subject_id: subjectId, module } },
            body: { role_rank: rank },
          }),
        );
      }
      setVersion((current) => current + 1);
      toast.success(strings.saved);
    } catch (cause: unknown) {
      toast.warning(failure(cause, strings.requestFailed));
    } finally {
      setBusy(false);
      setPending(null);
    }
  }

  return (
    <Stack gap={3}>
      <h2 data-terp="admin-section-title">{strings.moduleAccessTitle}</h2>
      <span data-terp="tile-note">{strings.moduleAccessDescription}</span>
      {loading && <LoadingState />}
      {!loading && error !== null && <Alert tone="danger">{error}</Alert>}
      {!loading && error === null && assignable.length === 0 && (
        <Alert tone="info">{strings.moduleAccessNoneAssignable}</Alert>
      )}
      {assignable.map((row) => (
        <ModuleStrip
          key={row.name}
          row={row}
          held={held}
          floor={floor}
          busy={busy}
          onPick={onPick}
        />
      ))}
      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(open) => {
          if (!open) setPending(null);
        }}
        onConfirm={() => {
          if (pending === null) return;
          void write(pending.module, pending.kind === "assign" ? pending.rank : null);
        }}
        title={
          pending?.kind === "assign"
            ? strings.moduleAccessConfirmTitle
                .replace("{role}", pending.role)
                .replace("{module}", pending.label)
            : strings.moduleAccessRevokeTitle.replace("{module}", pending?.label ?? "")
        }
        description={
          pending?.kind === "assign" ? strings.moduleAccessConfirm : strings.moduleAccessRevoke
        }
        confirmLabel={strings.confirm}
        destructive={pending?.kind === "assign"}
        isPending={busy}
      />
    </Stack>
  );
}
