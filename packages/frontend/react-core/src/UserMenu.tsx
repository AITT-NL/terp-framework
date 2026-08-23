import { Icon } from "./icons";
import { injectTerpStyles } from "./styles";
import { useAuth } from "./TerpProvider";
import { Avatar } from "./ui/Avatar";
import { Menu, MenuItem } from "./ui/Menu";
import { useStrings } from "./uiText";

injectTerpStyles();

/**
 * Re-exported from where the tile now lives. It was public under this name before `Avatar`
 * existed, and moving a published export to another module is a breaking change for no
 * reason — the tile is what needed one home, not the name.
 */
export { userInitials } from "./ui/Avatar";

export interface UserMenuProps {
  /** Icon-rail mode: show only the avatar on the trigger (the shell's collapsed state). */
  collapsed?: boolean;
  /** Opens the settings / profile page; rendered as the menu's first item when provided. */
  onSettings?: () => void;
  /**
   * Open the panel on mount (uncontrolled), the shape every other disclosure in the package
   * takes. It is also the only way to render the panel deterministically, and the panel is
   * where this component's own geometry lives — so without it those rules ship unpainted by
   * either visual lane, which is the state the calendar was in for two stages.
   */
  defaultOpen?: boolean;
}

/** The signed-in user's account menu. */
export function UserMenu({ collapsed = false, onSettings, defaultOpen }: UserMenuProps = {}) {
  const auth = useAuth();
  const strings = useStrings();
  const user = auth.currentUser();
  if (user === null) {
    return null;
  }

  const trigger = (
    <>
      <Avatar from={user.email} size="sm" />
      {!collapsed && (
        <span data-terp="user-menu-identity">
          <span data-terp="user-menu-email">{user.email}</span>
          <span data-terp="user-menu-role">{user.role_name}</span>
        </span>
      )}
    </>
  );

  return (
    <Menu
      trigger={trigger}
      // Only in the icon rail, and the asymmetry is the point. `aria-label` REPLACES the
      // subtree text in the accessible name, so in the expanded trigger — which renders the
      // user's email and role as visible text — naming it "Account menu" hid both from anyone
      // relying on the name, and left a voice-control user with no spoken label that matches
      // what they can see (WCAG 2.5.3, Label in Name). Collapsed there is nothing to hide: the
      // avatar initials are aria-hidden, so without this the button would have no name at all.
      triggerLabel={collapsed ? strings.accountMenu : undefined}
      placement="top"
      align="start"
      defaultOpen={defaultOpen}
      // This component's rendered root is Menu's popover wrapper — it adds no element of its
      // own — so it names that root through Menu. The icon-rail mode is a variant of the same
      // component rather than a different one, so it is data-variant on the same marker; and
      // the trigger and the panel are then reachable from the sheet, which is what let both
      // `triggerStyle` and `panelStyle` be deleted. The panel needs the owner attribute
      // Popover stamps for it: it is portalled to document.body, so no descendant selector
      // from this side of the tree could ever reach it.
      data-terp="user-menu"
      data-variant={collapsed ? "collapsed" : undefined}
      data-owner="user-menu"
    >
      {({ close }) => (
        <>
          {/* role="group": a role="menu" may own only menuitem / menuitemradio /
              menuitemcheckbox / group / separator, and this identity block is a plain div —
              so in menu mode assistive tech had no valid reason to reach it. A group needs no
              accessible name to be valid and has no default presentation, so this is an ARIA
              correction with no visual and no new UI string. */}
          <div role="group" data-terp="user-menu-header">
            <span>{user.email}</span>
            <span data-terp="user-menu-role">{user.role_name}</span>
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
