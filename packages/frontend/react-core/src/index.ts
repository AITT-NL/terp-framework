// Public surface of @terpjs/react-core — see README.md for the component catalog and
// usage conventions: the provider/hooks that wire a tree to @terpjs/contract, the
// capability gate, the authorization guard, the TanStack Router adapter, and the
// presentational shell + token-only UI primitives.
export { TerpProvider, useAuth, useTerpClient } from "./TerpProvider";
export type { TerpProviderProps } from "./TerpProvider";
export { canPerform, DEFAULT_RANK_THRESHOLDS } from "./capabilities";
export type { RankThresholds } from "./capabilities";
export { createAuthClient } from "./createAuthClient";
export type { AuthClientOptions, TokenGetter } from "./createAuthClient";
export { Authorized, useCan, useHasPermission, usePermissions } from "./Authorized";
export type { AuthorizedProps } from "./Authorized";
export { useResource } from "./useResource";
export type { Resource, ResourcePage, ResourceSource } from "./useResource";
export { useRecord } from "./useRecord";
export type { RecordResource, RecordSource } from "./useRecord";
export { useRealtimeChannel } from "./realtime";
export type {
  RealtimeChannelOptions,
  RealtimeChannelState,
  RealtimeStatus,
  RealtimeTransport,
} from "./realtime";
export { unwrap, unwrapOptional, ApiError } from "./unwrap";
export type { FetchResult } from "./unwrap";
export {
  formatDate,
  formatDateTime,
  formatNumber,
  useFormatDate,
  useFormatDateTime,
  useFormatNumber,
} from "./format";
export type { FormattableDate } from "./format";
export { ResourceList } from "./ResourceList";
export type { ResourceListProps } from "./ResourceList";
export { RequireAuth } from "./RequireAuth";
export type { RequireAuthProps } from "./RequireAuth";
export { groupNav, isDeclarationVisible, visibleNav } from "./nav";
export type { NavSection, NavVisibilityContext } from "./nav";
export { activeNavPath, isNavItemActive } from "./navActive";
export type { NavActiveCandidate } from "./navActive";
export {
  AppShell,
  SIDEBAR_STORAGE_KEY,
} from "./AppShell";
export type {
  AppShellProps,
  AppShellSlotContext,
  AppShellLinkContext,
  RenderBrandLink,
} from "./AppShell";
export { Icon, NavIcon, TerpMark, ICON_GLYPHS } from "./icons";
export type { IconProps, NavIconProps } from "./icons";
export { ProfileView } from "./ProfileView";
export { Breadcrumbs } from "./Breadcrumbs";
export type { BreadcrumbItem, BreadcrumbsProps, RenderBreadcrumbLink } from "./Breadcrumbs";
// Published by buildAppRouter; exported so a standalone story/test tree (or a bespoke
// shell) can provide the ambient link renderer the layout components default to.
export { NavLinkContext, useNavLink } from "./navLink";
export type { NavLinkRenderer } from "./navLink";
export { Page } from "./Page";
export type { PageProps } from "./Page";
export { LAYOUT_CONTRACTS } from "./layoutContract";
export type { LayoutContractSpec, LayoutSlotSpec } from "./layoutContract";
// `ResolvedLayout` is deliberately NOT exported: nothing hands one to app code, so it
// would be public surface a consumer can never hold.
export type { LayoutDeclaration, LayoutShellDeclaration } from "./layoutDeclaration";
export { PageActions } from "./PageActions";
export type { OverflowAction, PageActionsProps } from "./PageActions";
export { ModuleNav } from "./ModuleNav";
export type { ModuleNavProps, ModuleNavTab } from "./ModuleNav";
export { OverviewPage } from "./OverviewPage";
export type { OverviewPageProps } from "./OverviewPage";
export { DetailPage } from "./DetailPage";
export type { DetailPageProps } from "./DetailPage";
export { FormPage } from "./FormPage";
export type { FormPageProps } from "./FormPage";
export { SettingsPage } from "./SettingsPage";
export type { SettingsPageProps } from "./SettingsPage";
export { SplitPage, SplitPane } from "./SplitPage";
export type {
  SplitPageProps,
  SplitPaneProps,
  SplitPaneRole,
  SplitListWidth,
} from "./SplitPage";
export { HubPage, HubCard } from "./HubPage";
export type { HubPageProps, HubCardProps, RenderHubCardLink } from "./HubPage";
export {
  UiTextProvider,
  Trans,
  useStrings,
  useUiText,
  resolveUiText,
  resolveUiTextNode,
  DEFAULT_STRINGS,
} from "./uiText";
export type {
  UiText,
  UiTextNode,
  ResolveUiText,
  TerpStrings,
  TransProps,
  UiTextProviderProps,
} from "./uiText";
export { EmptyState } from "./EmptyState";
export type { EmptyStateProps } from "./EmptyState";
export { ErrorState, describeError } from "./ErrorState";
export type { ErrorStateProps } from "./ErrorState";
export { ErrorMessagesProvider, useErrorMessage, DEFAULT_ERROR_MESSAGES } from "./errorMessages";
export type { ErrorMessages, ErrorMessagesProviderProps } from "./errorMessages";
export { ConfirmDialog } from "./ConfirmDialog";
export { Disclosure } from "./Disclosure";
export type { DisclosureProps } from "./Disclosure";
export type { ConfirmDialogProps } from "./ConfirmDialog";
export { LoadingState, InlineSpinner } from "./LoadingState";
export type { LoadingStateProps, InlineSpinnerProps } from "./LoadingState";
export { ToastProvider, useToast } from "./toast";
export type { ToastApi, ToastOptions, ToastProviderProps, ToastVariant } from "./toast";
export { Button } from "./ui/Button";
export type { ButtonProps, ButtonSize, ButtonVariant } from "./ui/Button";
export { Input } from "./ui/Input";
export type { InputProps } from "./ui/Input";
export { Select } from "./ui/Select";
export type { SelectProps, SelectOption } from "./ui/Select";
export { Textarea } from "./ui/Textarea";
export type { TextareaProps } from "./ui/Textarea";
export { Popover } from "./ui/Popover";
export type { PopoverAlign, PopoverPlacement, PopoverProps } from "./ui/Popover";
export { Menu, MenuItem } from "./ui/Menu";
export type { MenuItemProps, MenuProps } from "./ui/Menu";
export { Combobox } from "./ui/Combobox";
export type { ComboboxOption, ComboboxProps } from "./ui/Combobox";
export { DatePicker, DateRangePicker } from "./ui/DatePicker";
export type { DatePickerProps, DateRangePickerProps, DateRangeValue } from "./ui/DatePicker";
export { Checkbox } from "./ui/Checkbox";
export type { CheckboxProps } from "./ui/Checkbox";
export { Radio, RadioGroup } from "./ui/Radio";
export type { RadioGroupProps, RadioOption, RadioProps } from "./ui/Radio";
export { Switch } from "./ui/Switch";
export type { SwitchProps } from "./ui/Switch";
export { Tabs } from "./ui/Tabs";
export type { TabItem, TabsProps } from "./ui/Tabs";
export { Avatar } from "./ui/Avatar";
export type { AvatarProps } from "./ui/Avatar";
export { Badge } from "./ui/Badge";
export type { BadgeProps, BadgeTone } from "./ui/Badge";
export { Card } from "./ui/Card";
export type { CardProps, CardVariant } from "./ui/Card";
export { Tooltip } from "./ui/Tooltip";
export type { TooltipProps } from "./ui/Tooltip";
export { Alert } from "./ui/Alert";
export type { AlertProps, AlertTone } from "./ui/Alert";
export { Markdown } from "./ui/Markdown";
export type { MarkdownProps } from "./ui/Markdown";
export { saveBlob, useEndpointDownload, fetchDownload, downloadUrl } from "./download";
export { copyText, useCopyToClipboard, COPIED_FEEDBACK_MS } from "./clipboard";
export type { CopyToClipboard } from "./clipboard";
export type { DownloadTarget } from "./download";
export { Heading, Text, Code, Link } from "./typography";
export type {
  HeadingProps,
  HeadingLevel,
  HeadingSize,
  TextProps,
  TextTone,
  TextSize,
  CodeProps,
  LinkProps,
} from "./typography";
export { Field } from "./Field";
export type { FieldProps } from "./Field";
export { Stack, Grid, Divider, DetailList, DetailListGroup } from "./layout";
export type {
  StackProps,
  GridProps,
  GridColumns,
  GridMinColumn,
  DividerProps,
  Responsive,
  DetailListProps,
  DetailListGroupProps,
  DetailListLayout,
  DetailItem,
  SpaceToken,
} from "./layout";
export {
  buildAppRouter,
  DEFAULT_ROLE_RANKS,
  PROFILE_PATH,
  useRouteParam,
  useRouteParams,
  useRouteSearch,
  useTerpNavigate,
} from "./router";
export type { BuildAppRouterOptions } from "./router";
// The generated `routes.gen.d.ts` augments TerpRouteTable (ADR 0092); the derived types
// are exported so an app can name a route path or a param object in its own signatures.
export type {
  TerpNavigateTarget,
  TerpRouteParamName,
  TerpRouteParams,
  TerpRoutePath,
  TerpRouteSearch,
  TerpRouteSearchKey,
  TerpRouteSearchTable,
  TerpRouteTable,
} from "./routeTypes";
export { LoginView } from "./LoginView";
export type { DevCredentials, LoginViewProps } from "./LoginView";
export {
  DEFAULT_SSO_CALLBACK_PATH,
  fetchSsoAuthorizationUrl,
  completeSsoCallback,
  isSsoCallbackLocation,
  parseSsoCallback,
} from "./sso";
export type { SsoCallbackParams, SsoProvider } from "./sso";
export { useSso } from "./TerpProvider";
export type { SsoSession } from "./TerpProvider";
export { FileUpload, useFileDownload, uploadFile, fetchFileContent } from "./files";
export type { FileMeta, FileUploadProps } from "./files";
export { collectModules, renderTerpApp, withAdminArea } from "./bootstrap";
export type { AdminAreaSections, RenderTerpAppOptions, TerpModule } from "./bootstrap";
export { adminModule } from "./admin/module";
export { AdminHub } from "./admin/AdminHub";
export { UsersAdmin } from "./admin/UsersAdmin";
export { UserCreate } from "./admin/UserCreate";
export { UserDetail } from "./admin/UserDetail";
export { GroupsAdmin } from "./admin/GroupsAdmin";
export { GroupCreate } from "./admin/GroupCreate";
export { GroupDetail } from "./admin/GroupDetail";
export { AuditLogAdmin } from "./admin/AuditLogAdmin";
export { ThemeProvider, ThemeToggle, useTheme, THEME_STORAGE_KEY } from "./theme";
export type { Theme, ThemeProviderProps, ThemeToggleProps } from "./theme";
export {
  LocaleProvider,
  defineAppLocales,
  LanguageSwitcher,
  useLocale,
  LOCALE_EN,
  LOCALE_NL,
  LOCALE_STORAGE_KEY,
} from "./locale";
export type {
  AppI18nDeclaration,
  LocaleCatalog,
  LocaleProviderProps,
  LanguageSwitcherProps,
} from "./locale";
export { UserMenu, userInitials } from "./UserMenu";
export type { UserMenuProps } from "./UserMenu";

// DataView — the repository-driven data-collection surface (see src/dataview/README.md).
export * from "./dataview";
