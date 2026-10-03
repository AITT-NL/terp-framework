import { createContext, useCallback, useContext, useMemo } from "react";
import type { ReactNode } from "react";
import type { FrameworkText, UiText } from "@terpjs/contract";

export type { UiText } from "@terpjs/contract";

// The keys a manifest's `FrameworkText` may name are this table's, so a misspelt one is a
// typecheck error where the manifest is written rather than an empty label on screen. Only its
// plain-string keys: a nav label has no count to choose a plural form by.
declare module "@terpjs/contract" {
  interface TerpFrameworkStrings extends Pick<TerpStrings, FrameworkTextKey> {}
}

/**
 * A framework string whose wording depends on a count: one form per CLDR plural category.
 *
 * English and Dutch each have two categories, `one` and `other`; Polish has four. The form is
 * chosen by the count under the active locale's `Intl.PluralRules`, so "1 result" and
 * "2 results" are two sentences rather than one sentence with "(s)" in it, and `other` answers
 * for a category the catalog has no form for. Each form keeps the same `{placeholder}`s,
 * because a category is a grammatical class and not a number: in Russian, 21 takes the `one`
 * form.
 */
export type PluralText = Readonly<Partial<Record<Intl.LDMLPluralRule, string>>> & {
  readonly other: string;
};

/** Every CLDR plural category; a {@link PluralText} names its forms from these. */
const PLURAL_CATEGORIES: readonly string[] = ["zero", "one", "two", "few", "many", "other"];

/**
 * Refuse a count-bearing framework string that is not a {@link PluralText}.
 *
 * Structure only, and deliberately: which categories a language uses comes from the runtime's
 * ICU data, which differs between browsers and versions — French is `one`/`other` on some and
 * `one`/`many`/`other` on newer ones — so a check against it would pass a catalog in one browser
 * and blank the app in the next. The shipped catalogs are held to their languages' categories
 * by react-core's own tests instead, where the ICU is fixed. *where* names the table in the
 * message: a locale, or a provider given its strings directly.
 */
export function assertPluralShape(where: string, key: string, value: unknown): void {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(
      `${where} framework string "${key}" counts something, so it takes one form per plural ` +
        'category — at least { other: "…" }, usually { one: "…", other: "…" } — not a single string.',
    );
  }
  const forms = value as Record<string, unknown>;
  const stray = Object.keys(forms).find((category) => !PLURAL_CATEGORIES.includes(category));
  if (stray !== undefined) {
    throw new Error(
      `${where} framework string "${key}" has a "${stray}" form, which is not a plural ` +
        `category (${PLURAL_CATEGORIES.join(", ")}).`,
    );
  }
  for (const category of ["other", ...Object.keys(forms)]) {
    const form = forms[category];
    if (typeof form !== "string" || form.trim() === "") {
      throw new Error(
        `${where} framework string "${key}" has no "${category}" form` +
          (category === "other" ? ", which every language uses." : "."),
      );
    }
  }
}

/** Whether *text* is a {@link PluralText} rather than a {@link UiText}. */
export function isPluralText(text: UiText | PluralText): text is PluralText {
  return typeof text === "object" && "other" in text;
}

/** The `TerpStrings` keys that hold one plain string, which a `FrameworkText` may name. */
type FrameworkTextKey = {
  [K in keyof TerpStrings]: TerpStrings[K] extends string ? K : never;
}[keyof TerpStrings];

/**
 * A piece of user-facing text: either a plain string (used as-is) or a message
 * descriptor — a stable `id` for a translation catalog plus the source-language
 * `message` used as the fallback. Components accept `UiText` so an app can go
 * from hardcoded strings to a full i18n runtime without changing call sites.
 */
/** Resolves a {@link UiText} to the display string for the active locale. */
export type ResolveUiText = (text: UiText) => string;

/** Textual copy or an already-rendered rich node, for prose-bearing component slots. */
export type UiTextNode = UiText | ReactNode;

/**
 * Resolve a descriptor/string while leaving rich React content untouched. Components
 * with prose slots use this instead of making callers choose between localization and
 * inline emphasis/links.
 */
export function resolveUiTextNode(
  value: UiTextNode,
  resolve: ResolveUiText = resolveUiText,
): ReactNode {
  if (typeof value === "string") {
    return resolve(value);
  }
  if (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    "id" in value &&
    "message" in value &&
    typeof value.id === "string" &&
    typeof value.message === "string"
  ) {
    return resolve(value);
  }
  return value as ReactNode;
}

/** The default resolver: plain strings as-is, descriptors via their fallback `message`. */
/**
 * `{name}` placeholders in *template*, filled from *values*. A name *values* does not own is left
 * as written — including one every object inherits: `key in values` filled `{constructor}` with
 * the source text of `Object`. The one formatter for a framework string that counts or names
 * something (the DataView's ranges, the page sequence's steps), so a fix reaches every caller.
 */
export function fillPlaceholders(
  template: string,
  values: Readonly<Record<string, string | number>>,
): string {
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    Object.hasOwn(values, key) ? String(values[key]) : match,
  );
}

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
  /** Password reveal toggle, while the value is hidden. */
  showPassword: string;
  /** Password reveal toggle, while the value is visible. */
  hidePassword: string;
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
  /** Accessible name of a page's link to the previous item of its sequence; `{label}` is that item. */
  pageSequencePrevious: string;
  /** Accessible name of a page's link to the next item of its sequence; `{label}` is that item. */
  pageSequenceNext: string;
  /** A page's place in its sequence; `{current}` and `{total}` are replaced. */
  pageSequencePosition: string;
  /** A figure's change that is good news, read out after it (the pill's colour, as a word). */
  statFavourable: string;
  /** A figure's change that is bad news, read out after it (the pill's colour, as a word). */
  statUnfavourable: string;
  /** A figure's sparkline as text; `{points}` is the listed points, each a label and a value. */
  statTrend: string;
  /** The admin hub: names the total on the users and groups cards. */
  adminHubTotal: string;
  /** Default {@link ErrorState} title. */
  errorTitle: string;
  /** Title shown by `RequireAuth` when the backend did not answer the boot check. */
  backendUnreachableTitle: string;
  /** Explanation shown with {@link TerpStrings.backendUnreachableTitle}. */
  backendUnreachableDescription: string;
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
  /** Label of the application home/root page. */
  home: string;
  /** Accessible name of the sidebar `nav` landmark. */
  primaryNavigationLabel: string;
  /** The shell's skip link — the first thing a keyboard reaches, jumping past the chrome. */
  skipToContent: string;
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
  /**
   * {@link ThemeToggle} option: `midday`, the light theme. The key keeps the theme's earlier
   * name (`light`), so a catalog written before the rename still loads; the value is the new one.
   */
  themeLight: string;
  /** {@link ThemeToggle} option: `evening`, the slate dark theme (key from its earlier name, `dark`). */
  themeDark: string;
  /** {@link ThemeToggle} option: `night`, the near-black dark theme (key from its earlier name, `midnight`). */
  themeMidnight: string;
  /** {@link ThemeToggle} option: `twilight`, the dimmed violet dark theme. */
  themeTwilight: string;
  /** {@link ThemeToggle} option: the high-contrast theme. */
  themeContrast: string;
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
  /** Access pane: the sidebar/hub entry and its one-line description. */
  adminAccess: string;
  adminAccessDescription: string;
  /** Access pane: the tile for holding no rung in a module at all. */
  accessNoRung: string;
  /** Access pane: heading above what a rung adds over the one below it. */
  accessAdds: string;
  /** Access pane: the three kinds a delta is split into. */
  accessKindRead: string;
  accessKindWrite: string;
  accessKindDelete: string;
  /** Access pane: shown on a rung that grants nothing the rung below did not. */
  accessAddsNothing: string;
  /** Access pane: shown on a module that declares it is never per-module assignable. */
  accessNeverAssignable: string;
  /** Access pane: shown on a module that has not opted into per-module roles. */
  accessNotAssignable: string;
  /** Access pane: warns that some of the module's routes declared no operation; `{count}`. */
  accessUnexplainedRoutes: PluralText;
  /** Access pane: the note that this screen shows the declared model, not who holds what. */
  accessDeclaredOnly: string;
  /** Assignment panel: the section heading on a person's or group's detail screen. */
  moduleAccessTitle: string;
  /** Assignment panel: what a rung here does, and the two things it can never do. */
  moduleAccessDescription: string;
  /** Assignment panel: shown when no module has opted into per-module roles at all. */
  moduleAccessNoneAssignable: string;
  /** Assignment panel: a rung reaching this subject through a group it belongs to. */
  moduleAccessVia: string;
  /** Assignment panel: a held rung the app's declarations no longer support. */
  moduleAccessStale: string;
  /** Assignment panel: why a rung at or below the subject's global role changes nothing. */
  moduleAccessFloor: string;
  /** Assignment panel: confirmation before handing someone the most privileged rung. */
  moduleAccessConfirmTitle: string;
  moduleAccessConfirm: string;
  /** Assignment panel: confirmation of the rung being taken away again. */
  moduleAccessRevokeTitle: string;
  moduleAccessRevoke: string;
  /** Assignment panel: a rung held in a module that no longer accepts one. */
  moduleAccessOrphaned: string;
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
  /** Users admin: viewer role label. */
  roleViewer: string;
  /** Users admin: editor role label. */
  roleEditor: string;
  /** Users admin: administrator role label. */
  roleAdmin: string;
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
  /** Users admin: confirmation before changing a role; `{role}` is replaced. */
  changeRoleConfirm: string;
  /** Users admin: confirmation before deactivation. */
  deactivateUserConfirm: string;
  /** Users admin: confirmation before reactivation. */
  reactivateUserConfirm: string;
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
  /** Group detail: confirmation before removing a member. */
  removeMemberConfirm: string;
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
  /** Group detail: confirmation before revoking a permission. */
  revokeConfirm: string;
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
  /** Audit admin: expanded row's label for the request that caused the event. */
  requestLabel: string;
  /** Generic success toast after a saved mutation. */
  saved: string;
  /** Generic failure toast when a request did not go through. */
  requestFailed: string;
  /** Combobox: clears the single selection. */
  clearSelection: string;
  /** Combobox: clears every selection in multiple mode. */
  clearAllSelections: string;
  /** Combobox: removes one chosen option in multiple mode, prefixed to its label. */
  comboboxRemove: string;
  /** Combobox: shown in the listbox while options are being fetched. */
  comboboxLoading: string;
  /** Combobox: shown in the listbox when the filter matches nothing. */
  comboboxNoOptions: string;
  /** DatePicker: steps the calendar back one month. */
  previousMonth: string;
  /** DatePicker: steps the calendar forward one month. */
  nextMonth: string;
  /** DatePicker: trigger text before a date is chosen. */
  selectDate: string;
  /** DateRangePicker: trigger text before a range is chosen. */
  selectDateRange: string;
  // DataView. Framework copy like everything above, so a locale catalog translates it and the
  // completeness check requires it; `DataView`'s per-instance `strings` prop still wins. Kept
  // apart from the similar keys above (`loading`, `errorTitle`, `moreActions`,
  // `clearSelection`) on purpose: the English differs, and a translation may too.
  /** DataView: the search box's placeholder and accessible name. */
  dataViewSearchPlaceholder: string;
  /** DataView: clears the search box. */
  dataViewClearSearch: string;
  /** DataView: the toolbar action that resets the caller's filters. */
  dataViewClearFilters: string;
  /** DataView: the column-settings menu trigger. */
  dataViewViewOptions: string;
  /** DataView: heading of the column list inside the column-settings menu. */
  dataViewColumns: string;
  /** DataView: moves a column earlier; prefixed to the column's name. */
  dataViewMoveUp: string;
  /** DataView: moves a column later; prefixed to the column's name. */
  dataViewMoveDown: string;
  /** DataView: switches to the table layout. */
  dataViewTableView: string;
  /** DataView: switches to the card layout. */
  dataViewCardView: string;
  /** DataView: the page-size selector. */
  dataViewPageSize: string;
  /** DataView: the footer's result range; `{from}`, `{to}` and `{total}`, plural by `{total}`. */
  dataViewResultsRange: PluralText;
  /** DataView: the footer's page position; `{page}` and `{pages}` are replaced. */
  dataViewPageOf: string;
  /** DataView: pagination, to the first page. */
  dataViewFirstPage: string;
  /** DataView: pagination, one page back. */
  dataViewPreviousPage: string;
  /** DataView: pagination, one page forward. */
  dataViewNextPage: string;
  /** DataView: pagination, to the last page. */
  dataViewLastPage: string;
  /** DataView: the header checkbox that selects every row on the page. */
  dataViewSelectAllPage: string;
  /** DataView: a row's selection checkbox. */
  dataViewSelectRow: string;
  /** DataView: the selection count; `{count}` is replaced. */
  dataViewSelected: string;
  /** DataView: widens the selection to every result; `{total}`, plural by it. */
  dataViewSelectAllResults: PluralText;
  /** DataView: clears the row selection. */
  dataViewClearSelection: string;
  /** DataView: the row-action and batch-action overflow trigger. */
  dataViewMoreActions: string;
  /** DataView: the actions column header. */
  dataViewActions: string;
  /** DataView: a row's open button; `{label}` is replaced by the record's name. */
  dataViewOpenRow: string;
  /** DataView: opens a row's detail panel. */
  dataViewExpandRow: string;
  /** DataView: closes a row's detail panel. */
  dataViewCollapseRow: string;
  /** DataView: the empty state when the caller passes no `emptyMessage`. */
  dataViewEmpty: string;
  /** DataView: the first load's placeholder. */
  dataViewLoading: string;
  /** DataView: shown while a refetch replaces rows already on screen. */
  dataViewRefreshing: string;
  /** DataView: the error state's title. */
  dataViewErrorTitle: string;
  /** DataView: a column's resize handle; prefixed to the column's name. */
  dataViewResizeColumn: string;
  // The wording for the platform's own `AppError` codes, which `useErrorMessage` shows in place
  // of the backend's `detail`. An app's `errorMessages` map still wins for any code it names,
  // including these; a code neither side words falls back to the `detail`.
  /** Error code `bad_request`. */
  errorCodeBadRequest: string;
  /** Error code `validation_failed`. */
  errorCodeValidationFailed: string;
  /** Error code `invalid_token`. */
  errorCodeInvalidToken: string;
  /** Error code `authentication_required`. */
  errorCodeAuthenticationRequired: string;
  /** Error code `permission_denied`. */
  errorCodePermissionDenied: string;
  /** Error code `not_found`. */
  errorCodeNotFound: string;
  /** Error code `conflict`. */
  errorCodeConflict: string;
  /** Error code `stale_data`. */
  errorCodeStaleData: string;
}

export const DEFAULT_STRINGS: TerpStrings = {
  clearSelection: "Clear selection",
  clearAllSelections: "Clear all selections",
  comboboxRemove: "Remove",
  comboboxLoading: "Loading…",
  comboboxNoOptions: "No options",
  previousMonth: "Previous month",
  selectDate: "Select date",
  selectDateRange: "Select date range",
  nextMonth: "Next month",
  loading: "Loading...",
  emptyList: "Nothing here yet.",
  add: "Add",
  signOut: "Sign out",
  signIn: "Sign in",
  signingIn: "Signing in…",
  email: "Email",
  password: "Password",
  showPassword: "Show password",
  hidePassword: "Hide password",
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
  pageSequencePrevious: "Previous: {label}",
  pageSequenceNext: "Next: {label}",
  pageSequencePosition: "{current} of {total}",
  statFavourable: "favourable",
  statUnfavourable: "unfavourable",
  statTrend: "Over time: {points}",
  adminHubTotal: "Total",
  errorTitle: "Something went wrong.",
  backendUnreachableTitle: "The application cannot reach its server.",
  backendUnreachableDescription:
    "No answer came back from the API. It may still be starting, or stopped. "
    + "Reload once it is running.",
  confirm: "Confirm",
  cancel: "Cancel",
  successTitle: "Success",
  warningTitle: "Heads up",
  dismiss: "Dismiss",
  accountMenu: "Account menu",
  settings: "Settings",
  profile: "Profile",
  role: "Role",
  home: "Home",
  primaryNavigationLabel: "Primary",
  skipToContent: "Skip to content",
  collapseSidebar: "Collapse sidebar",
  expandSidebar: "Expand sidebar",
  openNavigation: "Open navigation",
  closeNavigation: "Close navigation",
  theme: "Theme",
  themeLight: "Midday",
  themeDark: "Evening",
  themeMidnight: "Night",
  themeTwilight: "Twilight",
  themeContrast: "High contrast",
  themeSystem: "System",
  language: "Language",
  admin: "Admin",
  adminUsers: "Users",
  adminUsersDescription: "Provision accounts, change roles, reset passwords",
  adminGroups: "Groups",
  adminGroupsDescription: "Bundle permissions; membership applies them",
  adminAudit: "Audit log",
  adminAuditDescription: "Every change: what, who, when",
  adminAccess: "Access",
  adminAccessDescription: "Which roles exist, and what each one may do per module",
  accessNoRung: "No access",
  accessAdds: "Adds over the tier below",
  accessKindRead: "View",
  accessKindWrite: "Change",
  accessKindDelete: "Delete",
  accessAddsNothing: "Nothing beyond the tier below",
  accessNeverAssignable: "Never assignable per module",
  accessNotAssignable: "Not assignable per module",
  accessUnexplainedRoutes: {
    one: "{count} action in this module has no description yet",
    other: "{count} actions in this module have no description yet",
  },
  accessDeclaredOnly:
    "This is what the application declares. It does not show who holds which role — open a person to see that.",
  moduleAccessTitle: "Access per module",
  moduleAccessDescription:
    "A role here applies in that one module and raises access, never lowers it. Modules that have not opted in are not listed.",
  moduleAccessNoneAssignable:
    "No module in this application accepts a role of its own, so there is nothing to set here.",
  moduleAccessVia: "Also {role} here, through {name}",
  moduleAccessStale: "Held, but has no effect: {reason}",
  moduleAccessFloor: "{role} everywhere already, so anything up to here changes nothing",
  moduleAccessConfirmTitle: "Give {role} in {module}?",
  moduleAccessConfirm:
    "This is the most far-reaching role the module has. Everything the tier below can do, plus what the tile lists.",
  moduleAccessRevokeTitle: "Take away the role in {module}?",
  moduleAccessRevoke:
    "Access in this module falls back to what the person's role gives them everywhere else.",
  moduleAccessOrphaned:
    "Still set to {role} in {module}, which no longer accepts a role of its own. It has no effect, and removing it is the only change left to make.",
  statusColumn: "Status",
  createdColumn: "Created",
  statusActive: "Active",
  statusDeactivated: "Deactivated",
  provisionUser: "Provision user",
  roleViewer: "Viewer",
  roleEditor: "Editor",
  roleAdmin: "Administrator",
  working: "Working…",
  makeRole: "Make {role}",
  resetPassword: "Reset password",
  newPassword: "New password",
  deactivate: "Deactivate",
  reactivate: "Reactivate",
  changeRoleConfirm: "Change this user's role to {role}?",
  deactivateUserConfirm: "Deactivate this account? Its active sessions will be revoked.",
  reactivateUserConfirm: "Reactivate this account?",
  groupName: "Name",
  description: "Description",
  members: "Members",
  createGroup: "Create group",
  deleteGroup: "Delete group",
  deleteGroupConfirm: "Delete this group? Its memberships and permission grants go with it.",
  addMember: "Add member",
  removeMember: "Remove",
  removeMemberConfirm: "Remove this member from the group?",
  userField: "User",
  userNotFound: "No account matches that email.",
  permissions: "Permissions",
  grantPermission: "Grant permission",
  permission: "Permission",
  revoke: "Revoke",
  revokeConfirm: "Revoke this permission from the group?",
  actionColumn: "Action",
  actorColumn: "Actor",
  targetColumn: "Target",
  whenColumn: "When",
  details: "Details",
  requestLabel: "Request",
  saved: "Saved",
  requestFailed: "The request failed. Try again.",
  dataViewSearchPlaceholder: "Search…",
  dataViewClearSearch: "Clear search",
  dataViewClearFilters: "Clear filters",
  dataViewViewOptions: "View options",
  dataViewColumns: "Columns",
  dataViewMoveUp: "Move up",
  dataViewMoveDown: "Move down",
  dataViewTableView: "Table view",
  dataViewCardView: "Card view",
  dataViewPageSize: "Rows per page",
  dataViewResultsRange: {
    one: "{from}–{to} of {total} result",
    other: "{from}–{to} of {total} results",
  },
  dataViewPageOf: "Page {page} of {pages}",
  dataViewFirstPage: "First page",
  dataViewPreviousPage: "Previous page",
  dataViewNextPage: "Next page",
  dataViewLastPage: "Last page",
  dataViewSelectAllPage: "Select all rows on this page",
  dataViewSelectRow: "Select row",
  dataViewSelected: "{count} selected",
  dataViewSelectAllResults: {
    one: "Select the {total} result",
    other: "Select all {total} results",
  },
  dataViewClearSelection: "Clear selection",
  dataViewMoreActions: "More actions",
  dataViewActions: "Actions",
  dataViewOpenRow: "Open details: {label}",
  dataViewExpandRow: "Expand row",
  dataViewCollapseRow: "Collapse row",
  dataViewEmpty: "Nothing to show.",
  dataViewLoading: "Loading…",
  dataViewRefreshing: "Refreshing…",
  dataViewErrorTitle: "Could not load data.",
  dataViewResizeColumn: "Resize column",
  errorCodeBadRequest: "The request could not be processed.",
  errorCodeValidationFailed: "Some fields are invalid. Check the form and try again.",
  errorCodeInvalidToken: "Your session is invalid. Sign in again.",
  errorCodeAuthenticationRequired: "Sign in to continue.",
  errorCodePermissionDenied: "You do not have permission to do this.",
  errorCodeNotFound: "This item could not be found.",
  errorCodeConflict: "This conflicts with the current state. Refresh and try again.",
  errorCodeStaleData: "This item was changed by someone else. Refresh and try again.",
};

interface UiTextContextValue {
  strings: TerpStrings;
  resolveText: ResolveUiText;
  /** The locale whose plural rules choose a {@link PluralText}'s form. */
  locale: string;
}

const UiTextContext = createContext<UiTextContextValue>({
  strings: DEFAULT_STRINGS,
  resolveText: resolveUiText,
  locale: "en",
});

export interface UiTextProviderProps {
  /** Per-key overrides of the framework's own strings (e.g. translations). */
  strings?: Partial<TerpStrings>;
  /**
   * Custom {@link UiText} resolver — the hook for a real i18n runtime: pass a
   * function that looks descriptors up in the active locale's catalog
   * (falling back to `message`). Defaults to {@link resolveUiText}. It is handed the app's
   * strings and descriptors only: a manifest's `FrameworkText` is answered from `strings`
   * before it is reached (see {@link useUiText}).
   */
  resolveText?: ResolveUiText;
  /**
   * The locale code the `strings` are in, whose plural rules choose a {@link PluralText}'s
   * form. `LocaleProvider` passes its active locale; without one the parent's applies, and
   * at the root that is English.
   */
  locale?: string;
  children: ReactNode;
}

/**
 * The locale seam. react-core components read all their own strings and
 * resolve all `UiText` props through this context; without a provider they
 * use the bundled English defaults. An app localises by wrapping its tree
 * once — no per-component wiring, no i18n dependency inside react-core.
 */
export function UiTextProvider({ strings, resolveText, locale, children }: UiTextProviderProps) {
  const parent = useContext(UiTextContext);
  const value = useMemo<UiTextContextValue>(() => {
    // A table given here directly has not been through LocaleProvider's check, and a
    // count-bearing key written the old way, as one string, would render nothing usable.
    for (const [key, supplied] of Object.entries(strings ?? {})) {
      if (typeof DEFAULT_STRINGS[key as keyof TerpStrings] !== "string") {
        assertPluralShape("UiTextProvider", key, supplied);
      }
    }
    return {
      strings: { ...parent.strings, ...strings },
      resolveText: resolveText ?? parent.resolveText,
      locale: locale ?? parent.locale,
    };
  }, [parent, strings, resolveText, locale]);
  return <UiTextContext.Provider value={value}>{children}</UiTextContext.Provider>;
}

/** The framework strings for the active locale (defaults merged with any overrides). */
export function useStrings(): TerpStrings {
  return useContext(UiTextContext).strings;
}

/**
 * The form of a {@link PluralText} the active locale's grammar gives *count*.
 *
 * `other` answers for a category the text has no form for — a catalog written against another
 * engine's plural data, or one that leaves a rare category out — so a count always renders a
 * sentence. For an app that renders a count-bearing framework string itself, read from
 * {@link useStrings}.
 */
export function usePlural(): (text: PluralText, count: number) => string {
  const { locale } = useContext(UiTextContext);
  return useMemo(() => {
    const rules = new Intl.PluralRules(locale);
    return (text: PluralText, count: number) => text[rules.select(count)] ?? text.other;
  }, [locale]);
}

/**
 * The active {@link UiText} resolver — call it on any `UiText` prop before rendering, and on a
 * manifest's navigation label, which may also be a {@link FrameworkText}.
 *
 * A `FrameworkText` is answered here, from the same table {@link useStrings} returns, and never
 * reaches the resolver a provider was given. That resolver is the app's: `LocaleProvider`'s
 * treats a descriptor's `message` as the app's source-locale text and looks every other locale
 * up in the app's messages, and framework copy is neither. A key the table does not have
 * throws rather than rendering an empty label; the type already refuses one, so this is what
 * holds a manifest the typecheck never saw.
 */
export function useUiText(): (text: UiText | FrameworkText) => string {
  const { strings, resolveText } = useContext(UiTextContext);
  return useCallback(
    (text: UiText | FrameworkText) => {
      if (typeof text === "string" || !("framework" in text)) {
        return resolveText(text);
      }
      if (!Object.hasOwn(strings, text.framework)) {
        throw new Error(
          `FrameworkText names "${text.framework}", which is not a framework string. ` +
            "Name a TerpStrings key (for example \"admin\"); an app's own copy is a " +
            "{ id, message } descriptor in frontend/i18n.json.",
        );
      }
      const value: unknown = strings[text.framework];
      if (typeof value !== "string") {
        throw new Error(
          `FrameworkText names "${text.framework}", which counts something and has one form ` +
            "per plural category. A navigation label is one string; name a plain one.",
        );
      }
      return value;
    },
    [strings, resolveText],
  );
}

/** Props for {@link Trans}: one stable catalog id and its source-language fallback. */
export interface TransProps {
  id: string;
  message: string;
}

/** Render authored copy through the active locale resolver, including plain JSX body text. */
export function Trans({ id, message }: TransProps) {
  const resolve = useUiText();
  return <>{resolve({ id, message })}</>;
}
