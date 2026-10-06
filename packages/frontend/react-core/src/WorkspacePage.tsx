import type { ReactNode } from "react";

import { LayoutSlotContext } from "./layoutContract";
import { Page } from "./Page";
import type { PageProps } from "./Page";
import { injectTerpStyles } from "./styles";
import { useUiText } from "./uiText";
import type { UiText } from "./uiText";

injectTerpStyles();

export type WorkspacePageProps = Omit<PageProps, "measure"> & {
  /** Parent trail for a workspace nested below a hub; aliases `Page`'s `breadcrumbs`. */
  parents?: PageProps["breadcrumbs"];
  /**
   * The workspace: one {@link CanvasHost}, or a framework state while it loads or fails.
   *
   * The body takes every pixel the shell leaves below the band, and the canvas takes the
   * body. Under a layout contract nothing else is admitted, because a second block beside the
   * canvas would have to share a height nobody declared.
   */
  children: ReactNode;
};

/**
 * The workspace archetype: one canvas that fills the screen (ADR 0179).
 *
 * For the screen whose work IS a surface rather than a list or a record: a diagram of nodes
 * and the connections between them, a floor plan, a planning board. Every other archetype
 * lays its body out as blocks that take the height of their content, and a canvas has no
 * content height of its own — it takes the box it is given — so before this a canvas could
 * only be sized with an inline style, which app code may not write.
 *
 * The frame is the ordinary page band, trail, actions and summary included. Below it the body
 * fills the rest of the shell's content column: the shell's main area becomes a flex column
 * when it holds a workspace (the same `:has()` scoping the page-sequence bar uses, so no other
 * page changes), the page grows into it, and the {@link CanvasHost} grows into the page.
 * Standalone, outside a shell, the canvas keeps a floor of 24rem.
 *
 * It provides `LayoutSlotContext` like `DashboardPage`: `Page` verifies the body's children
 * against the contract's `WorkspacePage` slot and stamps `data-fill` on the article when it is
 * the workspace's.
 */
export function WorkspacePage({ parents, breadcrumbs, ...page }: WorkspacePageProps): ReactNode {
  return (
    <LayoutSlotContext.Provider value="WorkspacePage">
      <Page {...page} breadcrumbs={parents ?? breadcrumbs} />
    </LayoutSlotContext.Provider>
  );
}

export interface CanvasHostProps {
  /**
   * The canvas's accessible name.
   *
   * Required: the host is a `<section>`, so a landmark, and an unnamed one is an entry in a
   * screen reader's landmark list that says nothing about what is on it.
   */
  label: UiText;
  /**
   * The canvas itself: an `<svg>` the app draws, or the root of a canvas component.
   *
   * Each child is laid over the whole host (absolutely, inset 0), so a component that sizes
   * itself to its container gets the full box and an `<svg>` scales by its `viewBox`. The
   * host's subtree is the app's to compose, as a `Card`'s body is: the contract governs the
   * workspace's direct children, not what is drawn on the canvas.
   */
  children: ReactNode;
}

/**
 * The surface a {@link WorkspacePage} fills: a named, bounded region that takes the page's
 * remaining height and lays its content over the whole of it.
 *
 * It paints from tokens only — the surface fill, the hairline and the radius a `Card` uses —
 * so it reads as a block of the page in every theme, and it clips what is drawn on it, so a
 * canvas panned past its edge does not paint over the band. It renders no inline style.
 */
export function CanvasHost({ label, children }: CanvasHostProps) {
  const resolve = useUiText();
  return (
    <section data-terp="canvas-host" aria-label={resolve(label)}>
      {children}
    </section>
  );
}
