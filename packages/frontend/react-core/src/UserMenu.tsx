import type { CSSProperties } from "react";

import { Icon } from "./icons";
import { useAuth } from "./TerpProvider";
import { Menu, MenuItem } from "./ui/Menu";
import { CONTROL_TEXT_STYLE } from "./ui/controlStyles";
import { useStrings } from "./uiText";

/** Initials for the avatar: the first letters of the email's local-part words. */
export function userInitials(email: string): string {
  const local = email.split("@")[0] ?? "";
  const words = local.split(/[._+-]+/).filter((word) => word.length > 0);
  const initials = words.slice(0, 2).map((word) => word[0]!.toUpperCase());
  return initials.join("") || "?";
}

const triggerStyle: CSSProperties = {
  ...CONTROL_TEXT_STYLE,
  display: "flex",
  alignItems: "center",
  justifyContent: "flex-start",
  gap: "var(--space-2)",
  width: "100%",
  boxSizing: "border-box",
  padding: "var(--space-2)",
  textAlign: "left",
  color: "var(--color-neutral-900)",
  background: "transparent",
  border: "1px solid transparent",
  borderRadius: "var(--radius-md)",
  cursor: "pointer",
};

const collapsedTriggerStyle: CSSProperties = {
  justifyContent: "center",
  gap: 0,
  padding: 0,
};

const avatarStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  width: "2rem",
  height: "2rem",
  flexShrink: 0,
  borderRadius: "var(--radius-full)",
  background: "var(--color-brand-primary)",
  color: "var(--color-brand-primary-contrast)",
  fontSize: "var(--font-size-sm)",
  fontWeight: "var(--font-weight-medium)" as CSSProperties["fontWeight"],
};

const identityStyle: CSSProperties = { display: "grid", minWidth: 0, fontSize: "var(--font-size-sm)" };
const emailStyle: CSSProperties = { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" };
const roleStyle: CSSProperties = { color: "var(--color-neutral-600)" };
const panelIdentityStyle: CSSProperties = {
  display: "grid",
  gap: "var(--space-1)",
  padding: "var(--space-2)",
  marginBottom: "var(--space-1)",
  borderBottom: "1px solid var(--color-neutral-200)",
  fontSize: "var(--font-size-sm)",
  overflowWrap: "anywhere",
};

export interface UserMenuProps {
  /** Icon-rail mode: show only the avatar on the trigger (the shell's collapsed state). */
  collapsed?: boolean;
  /** Opens the settings / profile page; rendered as the menu's first item when provided. */
  onSettings?: () => void;
}

/** The signed-in user's account menu. */
export function UserMenu({ collapsed = false, onSettings }: UserMenuProps = {}) {
  const auth = useAuth();
  const strings = useStrings();
  const user = auth.currentUser();
  if (user === null) {
    return null;
  }

  const trigger = (
    <>
      <span aria-hidden="true" style={avatarStyle}>{userInitials(user.email)}</span>
      {!collapsed && (
        <span style={identityStyle}>
          <span style={emailStyle}>{user.email}</span>
          <span style={roleStyle}>{user.role_name}</span>
        </span>
      )}
    </>
  );

  return (
    <Menu
      trigger={trigger}
      triggerLabel={strings.accountMenu}
      placement="top"
      align="start"
      triggerStyle={collapsed ? { ...triggerStyle, ...collapsedTriggerStyle } : triggerStyle}
      panelStyle={{ minWidth: "14rem", padding: "var(--space-2)" }}
    >
      {({ close }) => (
        <>
          <div style={panelIdentityStyle}>
            <span>{user.email}</span>
            <span style={roleStyle}>{user.role_name}</span>
          </div>
          {onSettings !== undefined && (
            <MenuItem
              label={strings.settings}
              icon={<Icon name="user" />}
              onSelect={() => {
                close(true);
                onSettings();
              }}
            />
          )}
          <MenuItem label={strings.signOut} icon={<Icon name="logout" />} onSelect={() => void auth.logout()} />
        </>
      )}
    </Menu>
  );
}
