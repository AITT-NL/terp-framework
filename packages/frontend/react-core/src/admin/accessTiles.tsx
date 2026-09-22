import { NO_ACCESS } from "./accessModel";
import type { ModuleRow, ModuleRung, OperationKind } from "./accessModel";
import type { Tile } from "../ui/TileGroup";
import type { TerpStrings } from "../uiText";

/**
 * One module's ladder as tiles — shared by the screen that *explains* the model and the panel
 * that *assigns* from it.
 *
 * Shared deliberately rather than written twice. The two surfaces answer the same question in
 * different moods — "what does editor get here?" and "should this person be editor here?" — and
 * a reader who compared them would be entitled to expect the same answer. Two copies of this
 * mapping is exactly how they would stop matching.
 */

/** What each rung of a module hands over, as the tile body. */
export function RungBody({ rung, strings }: { rung: ModuleRung; strings: TerpStrings }) {
  if (rung.addsNothing) {
    // Said out loud rather than shown as an empty tile. A module whose policy only separates
    // read from write has an `admin` rung that buys nothing, and an administrator assigning it
    // expecting more has made a mistake this line prevents.
    return <span data-terp="tile-note">{strings.accessAddsNothing}</span>;
  }
  const kinds: [OperationKind, string][] = [
    ["read", strings.accessKindRead],
    ["write", strings.accessKindWrite],
    ["delete", strings.accessKindDelete],
  ];
  return (
    <>
      {kinds.map(([kind, label]) =>
        rung.added[kind].length === 0 ? null : (
          <span key={kind} data-terp="tile-delta">
            {/* Split by kind, because "may delete three things" is a different decision from
                "may read thirty" and a mixed list buries the destructive half in the middle of
                the harmless one. The destructive kind is last and carries its own tone. */}
            <strong>{label}:</strong> {rung.added[kind].map((o) => o.label).join(", ")}
          </span>
        ),
      )}
    </>
  );
}

/** The module's rungs as tiles, with a real "no access" tile first. */
export function tilesFor(row: ModuleRow, strings: TerpStrings): Tile[] {
  return [
    // A real tile, so revoking is exactly as reachable as granting.
    { value: NO_ACCESS, label: strings.accessNoRung },
    ...row.rungs.map((rung, index) => ({
      value: rung.role,
      label: rung.role,
      body: <RungBody rung={rung} strings={strings} />,
      // The most privileged rung carries the destructive framing. Deliberately inverted from a
      // plan picker, which highlights its top tier to move you up: this screen exists to help
      // someone choose the smallest tier that works.
      tone: index === row.rungs.length - 1 ? ("danger" as const) : ("neutral" as const),
    })),
  ];
}

/** The rung that is the top of the ladder, whose assignment is the one worth confirming. */
export function topRung(row: ModuleRow): string | null {
  return row.rungs.length === 0 ? null : row.rungs[row.rungs.length - 1].role;
}
