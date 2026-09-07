import { useId, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";

import { injectTerpStyles } from "../styles";
import { useUiText } from "../uiText";
import type { UiText } from "../uiText";

injectTerpStyles();

/** One tile: a rung, and what reaching it hands over. */
export interface Tile {
  value: string;
  label: UiText;
  /** What choosing this hands over. Rendered inside the tile, below the label. */
  body?: ReactNode;
  /**
   * `danger` for a choice whose consequence is destructive. It carries the visual weight a
   * subscription table would give its top plan, deliberately inverted: this control exists to
   * bias *down*, so the most privileged rung is the one that looks like a decision.
   */
  tone?: "neutral" | "danger";
}

interface TileGroupBase {
  /** Names the group for assistive technology. Required — an unlabelled group is unusable. */
  label: UiText;
  tiles: readonly Tile[];
}

/** The strip as a **control**: one tile is the current choice, and committing changes it. */
export interface TileChoiceProps extends TileGroupBase {
  readOnly?: false;
  /** The selected value, or `null` for none selected. */
  value: string | null;
  /**
   * Called when a tile is *committed* — clicked, or focused and confirmed with Space/Enter.
   * Never called by arrowing alone.
   */
  onCommit: (value: string) => void;
  /**
   * A value already reached some other way, marked as a floor rather than a selection. The
   * caller's own choice may sit below it and the floor still applies, so a strip that showed
   * only the direct selection would imply an authority the reader does not have.
   */
  floor?: string | null;
  disabled?: boolean;
}

/**
 * The strip as a **description**: the tiles explain what each rung hands over, and nothing in
 * it is selectable.
 *
 * A separate mode rather than a disabled control, because the two are different claims. A
 * disabled radiogroup announces a set of radio buttons with none of them checked — which tells
 * a screen-reader user they have failed to choose something, on a screen where there is
 * nothing to choose. This mode carries the same tiles with no selection semantics at all.
 *
 * It deliberately accepts no `value`: a highlighted tile that assistive technology cannot see
 * is a sighted-only fact, and the type is what stops one being passed here. A screen that
 * needs to show what someone *holds* wants the control, gated on whether the reader may
 * change it.
 */
export interface TileDescriptionProps extends TileGroupBase {
  readOnly: true;
}

export type TileGroupProps = TileChoiceProps | TileDescriptionProps;

function TileContent({ tile }: { tile: Tile }) {
  const resolve = useUiText();
  return (
    <>
      <span data-terp="tile-label">{resolve(tile.label)}</span>
      {tile.body !== undefined && <div data-terp="tile-body">{tile.body}</div>}
    </>
  );
}

function TileDescription({ label, tiles }: TileDescriptionProps) {
  const resolve = useUiText();
  return (
    <div data-terp="tile-group" role="group" aria-label={resolve(label)}>
      {tiles.map((tile) => (
        <div
          key={tile.value}
          data-terp="tile"
          data-tone={tile.tone === "danger" ? "danger" : undefined}
        >
          <TileContent tile={tile} />
        </div>
      ))}
    </div>
  );
}

function TileChoice({
  label,
  tiles,
  value,
  onCommit,
  floor = null,
  disabled = false,
}: TileChoiceProps) {
  const resolve = useUiText();
  const groupId = useId();
  const refs = useRef<(HTMLDivElement | null)[]>([]);
  const selectedIndex = tiles.findIndex((tile) => tile.value === value);
  // Focus starts on the selection, or on the first tile when there is none.
  const [focusIndex, setFocusIndex] = useState(() => (selectedIndex >= 0 ? selectedIndex : 0));

  function moveTo(index: number) {
    setFocusIndex(index);
    refs.current[index]?.focus();
  }

  function step(from: number, delta: number) {
    if (tiles.length === 0) return;
    // Wraps, because a strip is a closed set: arrowing past the end of four tiles and stopping
    // dead reads as a broken control rather than as a boundary.
    moveTo((from + delta + tiles.length) % tiles.length);
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (disabled) return;
    // The tile the key actually reached, not the one state believes is focused. A keydown fires
    // on the focused element and bubbles here, so the event target *is* the current tile —
    // whereas `focusIndex` is a render-time value that can lag the DOM by a tick, and acting on
    // it would arrow from the wrong place exactly when focus had just moved.
    const target = refs.current.findIndex((node) => node === event.target);
    const from = target === -1 ? focusIndex : target;

    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      event.preventDefault();
      step(from, 1);
      return;
    }
    if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      event.preventDefault();
      step(from, -1);
      return;
    }
    if (event.key === "Home") {
      event.preventDefault();
      moveTo(0);
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      moveTo(tiles.length - 1);
      return;
    }
    if (event.key === " " || event.key === "Enter") {
      event.preventDefault();
      const tile = tiles[from];
      if (tile !== undefined) onCommit(tile.value);
    }
  }

  return (
    <div
      data-terp="tile-group"
      role="radiogroup"
      aria-label={resolve(label)}
      aria-disabled={disabled || undefined}
      onKeyDown={onKeyDown}
    >
      {tiles.map((tile, index) => {
        const selected = tile.value === value;
        const isFloor = floor !== null && tile.value === floor;
        return (
          <div
            key={tile.value}
            id={`${groupId}-${tile.value}`}
            ref={(node) => {
              refs.current[index] = node;
            }}
            data-terp="tile"
            data-selected={selected || undefined}
            data-floor={isFloor || undefined}
            data-tone={tile.tone === "danger" ? "danger" : undefined}
            role="radio"
            aria-checked={selected}
            aria-disabled={disabled || undefined}
            // The roving tab stop: one tile is reachable by Tab and the arrows move within the
            // group, which is what a radiogroup is supposed to feel like.
            tabIndex={index === focusIndex && !disabled ? 0 : -1}
            onFocus={() => setFocusIndex(index)}
            onClick={() => {
              if (!disabled) onCommit(tile.value);
            }}
          >
            <TileContent tile={tile} />
          </div>
        );
      })}
    </div>
  );
}

/**
 * The whole set of rungs as tiles — either as a control with **manual activation**, or as a
 * description of what each rung hands over.
 *
 * A dropdown was the obvious control and it is the wrong one here: it hides that the options
 * exist until you open it, and it makes two of them impossible to compare. The tiles borrow the
 * shape of a plan picker, where "everything below, plus…" is the mechanic — and invert its
 * rhetoric, because a plan picker exists to move you up a tier and this exists to help someone
 * choose the smallest tier that works.
 *
 * Manual activation is the load-bearing accessibility decision of the control mode, not a
 * detail. A native radio group activates on arrow: focus moves and the value changes together.
 * Here the most privileged tile is behind a confirmation, so automatic activation would fire
 * that confirmation while someone was merely arrowing past it — the roving-tabindex pattern
 * with Space/Enter to commit is what makes the keyboard path match the pointer path.
 * `Home`/`End` jump to the ends, which is what a strip of five or six tiles needs to be usable
 * at all.
 */
export function TileGroup(props: TileGroupProps) {
  return props.readOnly === true ? <TileDescription {...props} /> : <TileChoice {...props} />;
}
