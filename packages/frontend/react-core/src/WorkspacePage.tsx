import type { ReactNode } from "react";

import type { BreadcrumbItem } from "./Breadcrumbs";
import { LayoutSlotContext } from "./layoutContract";
import { Page } from "./Page";
import type { PageProps } from "./Page";
import { injectTerpStyles } from "./styles";
import { useUiText } from "./uiText";
import type { UiText } from "./uiText";

injectTerpStyles();

export type WorkspacePageProps = Omit<PageProps, "breadcrumbs" | "measure"> & {
  /** Optional parent layers for a workspace nested below a hub or an area. */
  parents?: readonly (BreadcrumbItem & { to: string })[];
  /**
   * The workspace: one {@link CanvasHost}, or a framework state while it loads or fails, and a
   * `ConfirmDialog` for an action taken on it.
   *
   * The body takes every pixel the shell leaves below the band, and the canvas takes the
   * body. Under a layout contract nothing else is admitted, because a second block beside the
   * canvas would have to share a height nobody declared. One host, too: two would split the
   * height between them.
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
 * page changes), the page grows into it, and the {@link CanvasHost} grows into the page. A
 * loading, error or empty state in the canvas's place grows the same way, so the frame does
 * not jump when the canvas arrives. Standalone, outside a shell, the canvas keeps a floor of
 * 24rem.
 *
 * It takes its trail as `parents` and provides `LayoutSlotContext`, as `DashboardPage` does:
 * `Page` verifies the body's children against the contract's `WorkspacePage` slot and stamps
 * `data-fill` on the article when it is the workspace's.
 */
export function WorkspacePage({ parents, ...page }: WorkspacePageProps): ReactNode {
  return (
    <LayoutSlotContext.Provider value="WorkspacePage">
      <Page {...page} breadcrumbs={parents} />
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
   * The canvas itself: ONE `<svg>` the app draws, or the root of ONE canvas component.
   *
   * The host lays an inner layer over its whole box, absolutely at inset 0, so the layer has a
   * definite size whatever the page around it does, and the child is sized to 100% of that
   * layer. So an `<svg>` fills the box and scales its drawing by its `viewBox`, and a canvas
   * component whose root sizes itself to its container gets all of it. Every child takes the
   * whole layer, which is why the host takes one: a second sibling does not share the box, it
   * lands below the first, outside the visible area, and is clipped. A `ConfirmDialog` is the
   * exception and is left at its own size.
   *
   * The host's subtree is the app's to compose, as a `Card`'s body is: the contract governs the
   * workspace's direct children, not what is drawn on the canvas.
   */
  children: ReactNode;
}

/**
 * The surface a {@link WorkspacePage} fills: a named, bounded region that takes the page's
 * remaining height and lays its one canvas over the whole of it. A workspace holds one host.
 *
 * It paints from tokens only — the surface fill, the hairline and the radius a `Card` uses —
 * so it reads as a block of the page in every theme, and it clips what is drawn on it, so a
 * canvas panned past its edge does not paint over the band. Because it clips, a focus ring
 * drawn around the canvas would be clipped with it, so the host draws the framework's focus
 * ring on itself while the canvas has keyboard focus. It renders no inline style.
 */
export function CanvasHost({ label, children }: CanvasHostProps) {
  const resolve = useUiText();
  return (
    <section data-terp="canvas-host" aria-label={resolve(label)}>
      {/* The layer is what gives the canvas a definite box. The host's own height comes from
          flex growth, which a child's percentage height cannot resolve against, and a canvas
          library's root is positioned by the library's own sheet rather than by ours. The
          layer is ours alone, absolutely positioned at inset 0, so its size is definite. */}
      <div data-terp="canvas-host-layer">{children}</div>
    </section>
  );
}
