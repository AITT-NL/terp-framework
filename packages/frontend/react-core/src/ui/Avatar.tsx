import { injectTerpStyles } from "../styles";

injectTerpStyles();

/**
 * Two letters from an email's local part — `jane.doe@…` becomes `JD`, `admin@…` becomes `A`.
 *
 * Lives here rather than beside the account menu because it is what an avatar is made of, and both
 * places that render one needed it. Still exported under its own name; it was public before this
 * component existed.
 */
export function userInitials(email: string): string {
  const local = email.split("@")[0] ?? "";
  const words = local.split(/[._+-]+/).filter((word) => word.length > 0);
  const initials = words.slice(0, 2).map((word) => word[0]!.toUpperCase());
  return initials.join("") || "?";
}

export interface AvatarProps {
  /** The text initials are derived from when `initials` is omitted — an email or a name. */
  from?: string;
  /** Explicit initials, for a caller with better material than `from`. */
  initials?: string;
  /** `md` = 3.5rem, the profile header. `sm` = 2rem, the account menu. Default `md`. */
  size?: "sm" | "md";
}

/**
 * The initials tile.
 *
 * A merge rather than an addition: the framework already shipped this component twice, as eleven
 * identical declarations under `profile-avatar` and eleven more under `user-menu-avatar`, differing
 * only in a width, a height and a font size. Two markers became one and the inventory went DOWN.
 * That is the opposite of the `Section` / `Surface` decision, and for the opposite reason — those
 * had no consumer, this had two of them wearing different names for the same thing.
 *
 * **No `src`.** `/me` returns `email`, `role_name` and `role_rank` and carries no avatar URL, so an
 * image slot would be a prop with nothing behind it. Additive the day the payload grows one.
 *
 * The tile is `aria-hidden`: initials are a decoration for a name that is always rendered beside
 * them, and announcing "JD" before "jane.doe@example.com" adds a puzzle rather than information.
 * A caller that has no adjacent name has an unlabelled avatar, which is why this takes no label —
 * the fix there is to render the name, not to spell out the letters.
 */
export function Avatar({ from, initials, size = "md" }: AvatarProps) {
  return (
    <span
      aria-hidden="true"
      data-terp="avatar"
      // No attribute for the default, matching every other sized component here: `md` IS the base
      // rule, and stamping it would leave two places describing the standard tile.
      data-size={size === "md" ? undefined : size}
    >
      {initials ?? (from === undefined ? "?" : userInitials(from))}
    </span>
  );
}
