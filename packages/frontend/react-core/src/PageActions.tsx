import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { MEDIUM_VIEWPORT, NARROW_VIEWPORT } from "./breakpoints";
import { injectTerpStyles } from "./styles";
import { Button } from "./ui/Button";
import { Menu, MenuItem } from "./ui/Menu";
import { useStrings, useUiText } from "./uiText";
import type { UiText } from "./uiText";

injectTerpStyles();

export interface OverflowAction {
  /** Display label for the menu item. */
  label: UiText;
  /** Optional leading icon or glyph. */
  icon?: ReactNode;
  onSelect: () => void;
  /** Destructive actions are shown in the danger colour inside the overflow menu. */
  variant?: "default" | "destructive";
  disabled?: boolean;
}

export interface PageActionsProps {
  /** The single most important call-to-action, supplied by the page as a styled element. */
  primary?: ReactNode;
  /** Supporting action(s), supplied by the page as styled element(s). */
  secondary?: ReactNode;
  /**
   * Supporting actions as DESCRIPTIONS rather than elements, which is what lets the cluster
   * change form with the viewport: a label and an icon can be a button, an icon alone, or a
   * line in a menu, and the same tuple renders all three. An element cannot — by the time a
   * caller hands over a `<Button>` the label is inside someone else's tree, so `secondary`
   * below can only ever be shown or hidden.
   *
   * Prefer this over `secondary` for anything that should survive a narrow viewport.
   */
  secondaryActions?: readonly OverflowAction[];
  /** Rare or destructive actions, kept out of the primary click path. */
  overflow?: readonly OverflowAction[];
  className?: string;
}

/**
 * Which form the supporting actions take at this width.
 *
 * Read from the two cutovers rather than one: `labels` above the second, `icons` in the middle
 * region, `menu` below the first. The regions come out of asking NARROW first and MEDIUM
 * second — see ./breakpoints for why that is two queries and not three.
 *
 * `labels` is also the answer with no `window` at all, so a server render and a first paint
 * agree on the widest form and hydration only ever takes things away.
 */
type ActionDensity = "labels" | "icons" | "menu";

function readDensity(): ActionDensity {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return "labels";
  }
  if (window.matchMedia(NARROW_VIEWPORT).matches) {
    return "menu";
  }
  if (window.matchMedia(MEDIUM_VIEWPORT).matches) {
    return "icons";
  }
  return "labels";
}

function useActionDensity(): ActionDensity {
  const [density, setDensity] = useState(readDensity);
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    // Both cutovers, because a drag across the middle region crosses one of them without
    // touching the other and the cluster has to change form either way.
    const narrow = window.matchMedia(NARROW_VIEWPORT);
    const medium = window.matchMedia(MEDIUM_VIEWPORT);
    const onChange = () => setDensity(readDensity());
    narrow.addEventListener("change", onChange);
    medium.addEventListener("change", onChange);
    return () => {
      narrow.removeEventListener("change", onChange);
      medium.removeEventListener("change", onChange);
    };
  }, []);
  return density;
}

function actionKey(action: OverflowAction): string {
  return typeof action.label === "string" ? action.label : action.label.id;
}

/**
 * Standard right-aligned action cluster for page headers.
 *
 * The primary action keeps its label at every width, and that is a decision rather than an
 * oversight: it is the one thing the page is for, and a glyph or a menu line makes the main
 * act of the screen a guess or a second tap. Everything around it gives way instead —
 * `secondaryActions` drop to icons in the middle region and fold into the overflow menu below
 * the first cutover, where they sit above the page's own rare and destructive items.
 */
export function PageActions({
  primary,
  secondary,
  secondaryActions,
  overflow,
  className,
}: PageActionsProps) {
  const strings = useStrings();
  const resolve = useUiText();
  const density = useActionDensity();
  const supporting = secondaryActions ?? [];
  const rare = overflow ?? [];
  // Below the first cutover the supporting actions stop being buttons and become the top of
  // the menu. Order is deliberate: what the page offers first, then what it keeps back.
  const inMenu = density === "menu" ? [...supporting, ...rare] : rare;
  const asButtons = density === "menu" ? [] : supporting;
  const hasMenu = inMenu.length > 0;

  if (
    primary === undefined &&
    secondary === undefined &&
    supporting.length === 0 &&
    rare.length === 0
  ) {
    return null;
  }

  return (
    <div className={className} data-terp="page-actions">
      {hasMenu && (
        <Menu trigger="⋯" triggerLabel={strings.moreActions}>
          {({ close }) => (
            <>
              {inMenu.map((action) => (
                <MenuItem
                  key={actionKey(action)}
                  label={action.label}
                  icon={action.icon}
                  destructive={action.variant === "destructive"}
                  disabled={action.disabled}
                  onSelect={() => {
                    action.onSelect();
                    close(true);
                  }}
                />
              ))}
            </>
          )}
        </Menu>
      )}
      {asButtons.map((action) => {
        const label = resolve(action.label);
        // Icon-only still has to SAY what it is: the label moves from the box to the
        // accessible name and the tooltip rather than being dropped, so the control reads the
        // same to a screen reader at every width and hovers legibly for everyone else.
        return density === "icons" && action.icon !== undefined ? (
          <Button
            key={actionKey(action)}
            variant={action.variant === "destructive" ? "danger" : "secondary"}
            icon={action.icon}
            aria-label={label}
            title={label}
            disabled={action.disabled}
            onClick={action.onSelect}
          />
        ) : (
          <Button
            key={actionKey(action)}
            variant={action.variant === "destructive" ? "danger" : "secondary"}
            icon={action.icon}
            disabled={action.disabled}
            onClick={action.onSelect}
          >
            {label}
          </Button>
        );
      })}
      {secondary}
      {primary}
    </div>
  );
}
