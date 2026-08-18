import type { ReactNode } from "react";

import { injectTerpStyles } from "./styles";
import { Menu, MenuItem } from "./ui/Menu";
import { useStrings } from "./uiText";
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
  /** Rare or destructive actions, kept out of the primary click path. */
  overflow?: readonly OverflowAction[];
  className?: string;
}

/** Standard right-aligned action cluster for page headers. */
export function PageActions({ primary, secondary, overflow, className }: PageActionsProps) {
  const strings = useStrings();
  const hasOverflow = overflow !== undefined && overflow.length > 0;

  if (primary === undefined && secondary === undefined && !hasOverflow) {
    return null;
  }

  return (
    <div className={className} data-terp="page-actions">
      {hasOverflow && (
        <Menu trigger="⋯" triggerLabel={strings.moreActions}>
          {({ close }) => (
            <>
              {overflow.map((action) => (
                <MenuItem
                  key={typeof action.label === "string" ? action.label : action.label.id}
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
      {secondary}
      {primary}
    </div>
  );
}
