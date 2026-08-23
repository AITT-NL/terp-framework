/**
 * The bundled icon names, as data the contract publishes.
 *
 * Contract cannot import react-core — the dependency runs the other way — so the glyphs
 * themselves stay in react-core and only their NAMES live here. That split is what lets
 * `NavItem.icon` be a checked name on a manifest that knows nothing about React: an app naming
 * an icon this set does not contain gets a typecheck error where it used to get a silent letter
 * tile, and a future non-React adapter reads the same list.
 *
 * `as const` is load-bearing rather than stylistic. Without it the array widens to `string[]`,
 * {@link IconName} becomes `string`, and every check built on it still compiles while asserting
 * nothing at all — the whole change would ship and do nothing. That is what the
 * `@ts-expect-error` guard beside the glyph table in react-core exists to catch: remove the
 * `as const` here and the directive there becomes unused, which is itself an error.
 *
 * Kept in the glyph table's declaration order rather than sorted, so the two read as one list.
 * react-core holds the table to this set exhaustively in both directions with `satisfies`, so a
 * glyph added without a name here, or a name added without a glyph, is a compile error at the
 * table rather than a runtime blank.
 */
export const ICON_NAMES = [
  "home",
  "list",
  "folder",
  "users",
  "shield",
  "settings",
  "sun",
  "moon",
  "monitor",
  "moon-stars",
  "sunset",
  "contrast",
  "document",
  "chart",
  "calendar",
  "inbox",
  "audit",
  "hub",
  "plus",
  "edit",
  "trash",
  "search",
  "check",
  "x",
  "chevron-down",
  "chevron-right",
  "chevron-left",
  "arrow-left",
  "external",
  "logout",
  "user",
  "bell",
  "key",
  "globe",
  "lock",
  "tag",
  "mail",
  "refresh",
  "filter",
  "download",
  "upload",
  "star",
  "heart",
  "database",
  "code",
  "truck",
  "cart",
  "wallet",
  "map-pin",
  "clock",
  "link",
  "grid",
  "book",
  "briefcase",
  "building",
  "clipboard",
  "layers",
  "send",
  "phone",
  "image",
  "video",
  "music",
  "wrench",
  "zap",
  "eye",
  "eye-off",
] as const;

/**
 * A name {@link ICON_NAMES} contains — the type `NavItem.icon` and `Icon` accept.
 *
 * Deliberately NOT the type of `NavIcon.name`, which stays `string`. `NavIcon` falls back to the
 * label's initial in a tile, so an unknown name there is a designed, visible behaviour with a
 * specimen of its own; `Icon` renders nothing at all, which is silence, and silence is the thing
 * this type exists to make impossible.
 */
export type IconName = (typeof ICON_NAMES)[number];
