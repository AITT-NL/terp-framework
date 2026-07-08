import { createContext, useCallback, useContext, useMemo } from "react";
import type { ReactNode } from "react";

/**
 * A piece of user-facing text: either a plain string (used as-is) or a message
 * descriptor — a stable `id` for a translation catalog plus the source-language
 * `message` used as the fallback. Components accept `UiText` so an app can go
 * from hardcoded strings to a full i18n runtime without changing call sites.
 */
export type UiText = string | { id: string; message: string };

/** Resolves a {@link UiText} to the display string for the active locale. */
export type ResolveUiText = (text: UiText) => string;

/** The default resolver: plain strings as-is, descriptors via their fallback `message`. */
export function resolveUiText(text: UiText): string {
  return typeof text === "string" ? text : text.message;
}

/**
 * Every user-facing string the framework renders itself. Each key can be
 * overridden per app (or wholesale rerouted through {@link UiTextProvider}'s
 * `resolveText`), so react-core stays locale-agnostic: it ships English
 * defaults but never forces them.
 */
export interface TerpStrings {
  /** Body placeholder while a page's data loads. */
  loading: string;
  /** Default empty-list message. */
  emptyList: string;
  /** Label of the default single-field create button. */
  add: string;
  /** Label of the header sign-out button. */
  signOut: string;
  /** Login view heading and submit label. */
  signIn: string;
  /** Login submit label while the request is in flight. */
  signingIn: string;
  /** Login email placeholder. */
  email: string;
  /** Login password placeholder. */
  password: string;
  /** Login failure message. */
  signInFailed: string;
  /** Label of the dev-only button that fills the seeded development credentials. */
  fillDevCredentials: string;
  /** Prefix of an SSO provider button label ("Continue with {provider}"). */
  continueWith: string;
  /** Separator between the credentials form and the SSO provider buttons. */
  orSeparator: string;
  /** Message when an SSO login attempt fails. */
  ssoFailed: string;
  /** Label of the {@link FileUpload} button. */
  uploadFile: string;
  /** {@link FileUpload} button label while an upload is in flight. */
  uploading: string;
  /** Default message when the user may not access a route. */
  unauthorized: string;
  /** Accessible name of the breadcrumb `nav` landmark. */
  breadcrumbsLabel: string;
  /** Accessible name of intra-module secondary navigation. */
  moduleNavigationLabel: string;
  /** Accessible label of the page-actions overflow trigger. */
  moreActions: string;
  /** Default {@link ErrorState} title. */
  errorTitle: string;
  /** Default confirm-button label of {@link ConfirmDialog}. */
  confirm: string;
  /** Default cancel-button label of {@link ConfirmDialog}. */
  cancel: string;
  /** Default success-toast title. */
  successTitle: string;
  /** Default warning-toast title. */
  warningTitle: string;
  /** Accessible label of a toast's dismiss button. */
  dismiss: string;
  /** Accessible label of the {@link UserMenu} avatar trigger. */
  accountMenu: string;
  /** Label of the {@link UserMenu} item that opens the profile / settings page. */
  settings: string;
  /** Title of the built-in profile page (and its breadcrumb). */
  profile: string;
  /** Label of the profile page's role detail. */
  role: string;
  /** Accessible name of the sidebar `nav` landmark. */
  primaryNavigationLabel: string;
  /** Accessible label of the header toggle when it collapses the expanded sidebar. */
  collapseSidebar: string;
  /** Accessible label of the header toggle when it expands the collapsed sidebar. */
  expandSidebar: string;
  /** Accessible label of the header toggle when it opens the mobile navigation drawer. */
  openNavigation: string;
  /** Accessible label of the control that closes the mobile navigation drawer. */
  closeNavigation: string;
  /** Label of the {@link ThemeToggle} select. */
  theme: string;
  /** {@link ThemeToggle} option: the light theme. */
  themeLight: string;
  /** {@link ThemeToggle} option: the dark theme. */
  themeDark: string;
  /** {@link ThemeToggle} option: follow the OS preference. */
  themeSystem: string;
  /** Label of the {@link LanguageSwitcher} select. */
  language: string;
  /** The packaged admin area: nav label + hub title. */
  admin: string;
  /** Admin hub card / users overview title. */
  adminUsers: string;
  /** Admin hub: users card description. */
  adminUsersDescription: string;
  /** Admin hub card / groups overview title. */
  adminGroups: string;
  /** Admin hub: groups card description. */
  adminGroupsDescription: string;
  /** Admin hub card / audit overview title. */
  adminAudit: string;
  /** Admin hub: audit card description. */
  adminAuditDescription: string;
  /** Generic "Status" column header. */
  statusColumn: string;
  /** Generic "Created" column header. */
  createdColumn: string;
  /** Active-account status label. */
  statusActive: string;
  /** Deactivated-account status label. */
  statusDeactivated: string;
  /** Users admin: provision-form submit label. */
  provisionUser: string;
  /** Generic in-flight label for a pending mutation. */
  working: string;
  /** Users admin: change-role action; `{role}` is replaced by the role's name. */
  makeRole: string;
  /** Users admin: reset-password action + dialog confirm label. */
  resetPassword: string;
  /** Users admin: reset dialog's password field label. */
  newPassword: string;
  /** Users admin: deactivate action. */
  deactivate: string;
  /** Users admin: reactivate action. */
  reactivate: string;
  /** Groups admin: name field / column. */
  groupName: string;
  /** Groups admin: description field / column. */
  description: string;
  /** Groups admin: members column / detail section title. */
  members: string;
  /** Groups admin: create-form submit label. */
  createGroup: string;
  /** Groups admin: delete action. */
  deleteGroup: string;
  /** Groups admin: delete confirmation body. */
  deleteGroupConfirm: string;
  /** Group detail: add-member submit label. */
  addMember: string;
  /** Group detail: remove-member action. */
  removeMember: string;
  /** Group detail: the user field of the add-member form. */
  userField: string;
  /** Group detail: no account matched the typed email. */
  userNotFound: string;
  /** Group detail: permissions section title. */
  permissions: string;
  /** Group detail: grant-form submit label. */
  grantPermission: string;
  /** Group detail: permission field / column. */
  permission: string;
  /** Group detail: revoke-grant action. */
  revoke: string;
  /** Audit admin: action column. */
  actionColumn: string;
  /** Audit admin: actor column. */
  actorColumn: string;
  /** Audit admin: target column. */
  targetColumn: string;
  /** Audit admin: timestamp column. */
  whenColumn: string;
  /** Audit admin: expanded row's payload heading. */
  details: string;
  /** Generic success toast after a saved mutation. */
  saved: string;
  /** Generic failure toast when a request did not go through. */
  requestFailed: string;
}

export const DEFAULT_STRINGS: TerpStrings = {
  loading: "Loading...",
  emptyList: "Nothing here yet.",
  add: "Add",
  signOut: "Sign out",
  signIn: "Sign in",
  signingIn: "Signing in…",
  email: "Email",
  password: "Password",
  signInFailed: "Sign-in failed. Check your credentials.",
  fillDevCredentials: "Fill dev credentials",
  continueWith: "Continue with",
  orSeparator: "or",
  ssoFailed: "Single sign-on failed. Try again.",
  uploadFile: "Upload file",
  uploading: "Uploading…",
  unauthorized: "You do not have access to this page.",
  breadcrumbsLabel: "Breadcrumb",
  moduleNavigationLabel: "Module navigation",
  moreActions: "More actions",
  errorTitle: "Something went wrong.",
  confirm: "Confirm",
  cancel: "Cancel",
  successTitle: "Success",
  warningTitle: "Heads up",
  dismiss: "Dismiss",
  accountMenu: "Account menu",
  settings: "Settings",
  profile: "Profile",
  role: "Role",
  primaryNavigationLabel: "Primary",
  collapseSidebar: "Collapse sidebar",
  expandSidebar: "Expand sidebar",
  openNavigation: "Open navigation",
  closeNavigation: "Close navigation",
  theme: "Theme",
  themeLight: "Light",
  themeDark: "Dark",
  themeSystem: "System",
  language: "Language",
  admin: "Admin",
  adminUsers: "Users",
  adminUsersDescription: "Provision accounts, change roles, reset passwords",
  adminGroups: "Groups",
  adminGroupsDescription: "Bundle permissions; membership applies them",
  adminAudit: "Audit log",
  adminAuditDescription: "Every change: what, who, when",
  statusColumn: "Status",
  createdColumn: "Created",
  statusActive: "Active",
  statusDeactivated: "Deactivated",
  provisionUser: "Provision user",
  working: "Working…",
  makeRole: "Make {role}",
  resetPassword: "Reset password",
  newPassword: "New password",
  deactivate: "Deactivate",
  reactivate: "Reactivate",
  groupName: "Name",
  description: "Description",
  members: "Members",
  createGroup: "Create group",
  deleteGroup: "Delete group",
  deleteGroupConfirm: "Delete this group? Its memberships and permission grants go with it.",
  addMember: "Add member",
  removeMember: "Remove",
  userField: "User",
  userNotFound: "No account matches that email.",
  permissions: "Permissions",
  grantPermission: "Grant permission",
  permission: "Permission",
  revoke: "Revoke",
  actionColumn: "Action",
  actorColumn: "Actor",
  targetColumn: "Target",
  whenColumn: "When",
  details: "Details",
  saved: "Saved",
  requestFailed: "The request failed. Try again.",
};

interface UiTextContextValue {
  strings: TerpStrings;
  resolveText: ResolveUiText;
}

const UiTextContext = createContext<UiTextContextValue>({
  strings: DEFAULT_STRINGS,
  resolveText: resolveUiText,
});

export interface UiTextProviderProps {
  /** Per-key overrides of the framework's own strings (e.g. translations). */
  strings?: Partial<TerpStrings>;
  /**
   * Custom {@link UiText} resolver — the hook for a real i18n runtime: pass a
   * function that looks descriptors up in the active locale's catalog
   * (falling back to `message`). Defaults to {@link resolveUiText}.
   */
  resolveText?: ResolveUiText;
  children: ReactNode;
}

/**
 * The locale seam. react-core components read all their own strings and
 * resolve all `UiText` props through this context; without a provider they
 * use the bundled English defaults. An app localises by wrapping its tree
 * once — no per-component wiring, no i18n dependency inside react-core.
 */
export function UiTextProvider({ strings, resolveText, children }: UiTextProviderProps) {
  const parent = useContext(UiTextContext);
  const value = useMemo<UiTextContextValue>(
    () => ({
      strings: { ...parent.strings, ...strings },
      resolveText: resolveText ?? parent.resolveText,
    }),
    [parent, strings, resolveText],
  );
  return <UiTextContext.Provider value={value}>{children}</UiTextContext.Provider>;
}

/** The framework strings for the active locale (defaults merged with any overrides). */
export function useStrings(): TerpStrings {
  return useContext(UiTextContext).strings;
}

/** The active {@link UiText} resolver — call it on any `UiText` prop before rendering. */
export function useUiText(): ResolveUiText {
  const { resolveText } = useContext(UiTextContext);
  return useCallback((text: UiText) => resolveText(text), [resolveText]);
}
