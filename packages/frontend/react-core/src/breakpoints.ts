/**
 * The one viewport cutover the framework has, in the one place it is written.
 *
 * It was written in three: `AppShell` and `DataView` each declared
 * `const MOBILE_BREAKPOINT = "(max-width: 768px)"` verbatim — the duplication the diagnosis
 * named — and the responsive `Stack` props would have made a third copy, this time in the
 * stylesheet where the first two could not see it.
 *
 * ## Why the value is a literal and not `var(--breakpoint-md)`
 *
 * The contract publishes `--breakpoint-md: 768px`, and neither consumer can read it. CSS
 * forbids a custom property in a media-query condition, and `matchMedia` takes a string, so
 * a component would have to resolve the property off `document.documentElement` at runtime —
 * which is a layout read on every mount, breaks under SSR where there is no document, and
 * turns a static query into a value that can change after first paint.
 *
 * So the literal stays, and the drift it invites is gated instead:
 * `styles.test.ts` reads `--breakpoint-md` out of the contract's token sheet and refuses a
 * mismatch here or in the stylesheet. The token remains the published source of truth about
 * what the number IS; this module is the single place it is spelled for use.
 *
 * ## Why WIDE is a negation
 *
 * `NARROW` and `WIDE` have to partition the viewport exactly: a width that satisfies both
 * would render the shell's drawer beside a row-direction toolbar, and a width satisfying
 * neither would render nothing at all. Two independent queries cannot guarantee that — the
 * conventional pairing is `max-width: 767.98px` with `min-width: 768px`, which works but
 * makes the partition depend on an epsilon somebody chose, and picking one here would also
 * have moved the shell's existing behaviour at exactly 768px.
 *
 * `not all and (max-width: 768px)` is the complement of `NARROW` by construction. The
 * `not all and` spelling rather than the shorter `not (…)` because it is the form every
 * browser has supported since media queries existed, and this is a stylesheet a consumer
 * cannot patch.
 */

/** The condition both narrow-viewport components match on (`matchMedia`, so no `@media`). */
export const NARROW_VIEWPORT = "(max-width: 768px)";

/** The stylesheet's complement of {@link NARROW_VIEWPORT} — everything above the cutover. */
export const WIDE_VIEWPORT_QUERY = "not all and (max-width: 768px)";
