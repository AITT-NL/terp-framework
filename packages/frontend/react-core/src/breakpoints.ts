/**
 * The viewport cutovers the framework has, in the one place they are written.
 *
 * They were written in three: `AppShell` and `DataView` each declared
 * `const MOBILE_BREAKPOINT = "(max-width: 768px)"` verbatim — the duplication the diagnosis
 * named — and the responsive `Stack` props would have made a third copy, this time in the
 * stylesheet where the first two could not see it.
 *
 * ## Why the values are literals and not `var(--breakpoint-md)`
 *
 * The contract publishes `--breakpoint-md: 768px` and `--breakpoint-lg: 1024px`, and neither
 * consumer can read them. CSS forbids a custom property in a media-query condition, and
 * `matchMedia` takes a string, so a component would have to resolve the property off
 * `document.documentElement` at runtime — which is a layout read on every mount, breaks under
 * SSR where there is no document, and turns a static query into a value that can change after
 * first paint.
 *
 * So the literals stay, and the drift they invite is gated instead:
 * `tokens.guard.test.ts` reads `--breakpoint-md` and `--breakpoint-lg` out of the contract's
 * token sheet and refuses a mismatch here or in the stylesheet. The tokens remain the
 * published source of truth about what the numbers ARE; this module is the single place they
 * are spelled for use.
 *
 * ## Why WIDE and ROOMY are negations
 *
 * A cutover's two sides have to partition the viewport exactly: a width that satisfied both
 * would render the shell's drawer beside a row-direction toolbar, and a width satisfying
 * neither would render nothing at all. Two independent queries cannot guarantee that — the
 * conventional pairing is `max-width: 767.98px` with `min-width: 768px`, which works but
 * makes the partition depend on an epsilon somebody chose, and picking one here would also
 * have moved the shell's existing behaviour at exactly 768px.
 *
 * `not all and (max-width: N)` is the complement of `(max-width: N)` by construction. The
 * `not all and` spelling rather than the shorter `not (…)` because it is the form every
 * browser has supported since media queries existed, and this is a stylesheet a consumer
 * cannot patch.
 *
 * ## Why two cutovers still make no third query
 *
 * The page band wants three regions, not two: below 768 it drops its lead line and folds its
 * action cluster to a menu, between 768 and 1024 it keeps the cluster but shows icons alone,
 * and above 1024 it shows everything. The obvious spelling of a middle region is an
 * `and` of a min and a max — which reintroduces exactly the epsilon the cutover above refuses,
 * and, worse, needs a negation nested inside an `and` that Media Queries 3 has no syntax for.
 *
 * So the regions are not three queries; they are two cutovers applied in cascade order. A rule
 * block writes the narrow case unconditionally, `WIDE_VIEWPORT_QUERY` corrects it for
 * everything above the first cutover, and `ROOMY_VIEWPORT_QUERY` corrects it again for
 * everything above the second. The middle region is what the first correction leaves standing
 * when the second does not apply — never named, never queried, and therefore never able to
 * disagree with its neighbours about who owns 768px or 1024px.
 *
 * `matchMedia` callers get the same shape from the other end: a component asks `NARROW` first
 * and `MEDIUM` second, and the first match wins.
 */

/** The condition both narrow-viewport components match on (`matchMedia`, so no `@media`). */
export const NARROW_VIEWPORT = "(max-width: 768px)";

/** The stylesheet's complement of {@link NARROW_VIEWPORT} — everything above the first cutover. */
export const WIDE_VIEWPORT_QUERY = "not all and (max-width: 768px)";

/**
 * At or below the second cutover — narrow AND the middle region together. Asked after
 * {@link NARROW_VIEWPORT}, so a match that is not already narrow IS the middle region.
 */
export const MEDIUM_VIEWPORT = "(max-width: 1024px)";

/** The stylesheet's complement of {@link MEDIUM_VIEWPORT} — everything above the second cutover. */
export const ROOMY_VIEWPORT_QUERY = "not all and (max-width: 1024px)";
