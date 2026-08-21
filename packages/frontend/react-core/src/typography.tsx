import type { AnchorHTMLAttributes, HTMLAttributes, ReactNode } from "react";

import { useNavLink } from "./navLink";
import { injectTerpStyles } from "./styles";

injectTerpStyles();

/**
 * The prose primitives, and the gap they close is narrower than "we had no typography".
 *
 * A module could always render a `<p>` or a `<code>`. What it could not do is give either any
 * treatment: app modules may not write `style` or `className` (ADR 0059), and a bare element
 * carries no `data-terp`, so no rule in the sheet can reach it. The framework's own generated
 * home page shipped a bare `<p>` and a bare `<code>` for exactly that reason. So these are the
 * marker, and the marker is what makes the ink themeable.
 *
 * ## They are the first readers of the published type scale
 *
 * `--font-line-height-*` and `--font-letter-spacing-*` shipped in 0.7.0 and nothing read them —
 * the same shape as the motion tokens, and resolved differently, because the facts differ.
 * Every motion literal mapped exactly onto a token, so wiring them was inert. Here only 8 of
 * the sheet's 32 literals map: it writes `line-height` values of 1.2, 1.25, 1.3, 1.4 and 1.5,
 * and the published scale offers 1.2, 1.35, 1.5 and 1.7. Converting the eight that match and
 * leaving thirteen that do not would be a half-migration, and converting the rest means
 * *changing rendered line heights* across a dozen components — a deliberate typography pass
 * with its own baselines, not a token wiring done in passing.
 *
 * New components have no such problem: nothing depends on their metrics yet, so they adopt the
 * published scale and give it its first consumers. `tokens.guard.test.ts` tracks the remainder
 * as an exact list, so the reconciliation stays a decision somebody has to make rather than a
 * thing that quietly never happens.
 */

/** Semantic heading level. `1` is absent on purpose — see {@link Heading}. */
export type HeadingLevel = 2 | 3 | 4;

/** Type step for a heading, independent of its level. */
export type HeadingSize = "sm" | "base" | "lg" | "xl";

export interface HeadingProps extends Omit<HTMLAttributes<HTMLHeadingElement>, "style"> {
  /**
   * The semantic level, which decides the element.
   *
   * There is no `1`, and the reason is structural rather than stylistic: `Page` renders the
   * single `<h1>` of every routed view, and every routed view is a `Page` (the page-archetype
   * control refuses one that is not). A second `<h1>` in a body would give the document two
   * top-level headings and break the outline a screen-reader user navigates by — so the
   * component cannot express it.
   */
  level: HeadingLevel;
  /**
   * The type step, defaulting per level (`2` → `lg`, `3` → `base`, `4` → `sm`).
   *
   * Decoupled from `level` deliberately: the level is an outline fact and the size is a design
   * one, and forcing them together is what makes authors reach for the wrong element to get the
   * right size. A visually small `<h2>` is a legitimate thing to want.
   */
  size?: HeadingSize;
  children?: ReactNode;
}

const DEFAULT_HEADING_SIZE: Record<HeadingLevel, HeadingSize> = { 2: "lg", 3: "base", 4: "sm" };

/**
 * A section heading inside a page body — `h2`–`h4`, with its size a separate choice.
 *
 * `data-size` is stamped for every heading, which breaks the idiom the rest of the package
 * follows — density, Button's `md`, Grid's `auto`, Card's `boxed` and Text's own default all
 * leave the default unstamped because the base rule *is* the default. A heading has no single
 * default to fold into a base rule: the default depends on the level, so the base rule carries
 * the weight and metrics and every size carries its own step. Stamping all three is what keeps
 * the sheet from needing a rule per level as well as per size.
 */
export function Heading({ level, size, children, ...rest }: HeadingProps) {
  const Component = `h${level}` as "h2" | "h3" | "h4";
  const step = size ?? DEFAULT_HEADING_SIZE[level];
  return (
    <Component {...rest} data-terp="heading" data-size={step}>
      {children}
    </Component>
  );
}

/** Ink weight for body copy. */
export type TextTone = "default" | "muted" | "subtle";

/** Type step for body copy. */
export type TextSize = "xs" | "sm" | "base" | "lg";

export interface TextProps extends Omit<HTMLAttributes<HTMLElement>, "style"> {
  /** The rendered element — `"p"` by default; `"span"` for text inside a line. */
  as?: "p" | "span" | "div";
  /** Ink weight (default `"default"`; `"muted"` for secondary copy, `"subtle"` for hints). */
  tone?: TextTone;
  /** Type step (default `"base"`). */
  size?: TextSize;
  /**
   * Cap the line length for readability (default off).
   *
   * A measure is the one typographic control that is about the container rather than the text,
   * and it is enumerable here — `"narrow"` / `"base"` — rather than a length, so there are no
   * arbitrary column widths for the same reason `gap` is a token index.
   *
   * It caps a **block**, so it does nothing on `as="span"` — `max-width` has no effect on an
   * inline box. That combination is a no-op rather than an error, which is worth knowing because
   * the failure is silent; the visible cue is prose that simply never wraps where it was asked
   * to.
   */
  measure?: "narrow" | "base";
  children?: ReactNode;
}

/** Body copy with themeable ink — the thing a bare `<p>` in a module cannot be. */
export function Text({
  as: Component = "p",
  tone = "default",
  size = "base",
  measure,
  children,
  ...rest
}: TextProps) {
  return (
    <Component
      {...rest}
      data-terp="text"
      // `default` and `base` are the base rule, so their attributes would describe the default
      // twice — the idiom density, Button's `md`, Grid's `auto` and Card's `boxed` all use.
      data-tone={tone === "default" ? undefined : tone}
      data-size={size === "base" ? undefined : size}
      data-measure={measure}
    >
      {children}
    </Component>
  );
}

export interface CodeProps extends Omit<HTMLAttributes<HTMLElement>, "style"> {
  /**
   * Render as a block rather than inline.
   *
   * A block wraps the `<code>` in a `<pre>`, which is what preserves the whitespace — a
   * `<code>` alone collapses it, so a multi-line snippet in one runs together. `tabIndex={0}`
   * goes on the `<pre>` because it scrolls: a scrollable region that cannot be focused cannot
   * be scrolled by keyboard, which is SC 2.1.1.
   */
  block?: boolean;
  children?: ReactNode;
}

/** An identifier or a snippet, in the mono family, with whitespace preserved when `block`. */
export function Code({ block = false, children, ...rest }: CodeProps) {
  if (!block) {
    return (
      <code {...rest} data-terp="code">
        {children}
      </code>
    );
  }
  return (
    // tabIndex after the spread, not before: a caller removing it would leave a scroll
    // container no keyboard can reach, which is the SC 2.1.1 failure it exists to prevent.
    <pre {...rest} data-terp="code-block" tabIndex={0}>
      <code data-terp="code">{children}</code>
    </pre>
  );
}

export interface LinkProps extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "style" | "href"> {
  /** Destination. A path (`/records`) routes in-app; anything else is an external anchor. */
  to: string;
  /** Open an external destination in a new tab (ignored for in-app paths). */
  newTab?: boolean;
  children?: ReactNode;
}

/** Whether `to` is an in-app path rather than an external destination. */
function isInApp(to: string): boolean {
  return to.startsWith("/");
}

/** A scheme (`https:`, `mailto:`, `tel:`) or a same-page fragment — an anchor's own business. */
function isExternal(to: string): boolean {
  return to.startsWith("#") || /^[a-z][a-z0-9+.\-]*:/i.test(to);
}

/**
 * Refuse a destination that is neither, fail closed and directive.
 *
 * `to="records"` — no leading slash, no scheme — used to fall through to the external branch
 * and render a relative anchor: a full page reload to a URL resolved against wherever the user
 * happened to be, with the role-aware guard skipped. A caller writing that means the route, and
 * every route in a manifest is absolute, so the silent reload is never what was wanted. Loud is
 * strictly better, and it matches how `useRouteParam` and `useTerpNavigate` treat a path they
 * cannot honour.
 */
function assertRoutable(to: string): void {
  if (!isInApp(to) && !isExternal(to)) {
    throw new Error(
      `Link "to" must be an in-app path ("/records"), an absolute URL ` +
        `("https://example.com"), or a fragment ("#section") — got "${to}". A bare relative ` +
        "path renders an anchor that reloads the page and skips the router's guard; every " +
        "route a manifest declares is absolute, so add the leading slash.",
    );
  }
}

/**
 * A link with themeable ink, routing in-app paths through the surrounding router.
 *
 * Two things it exists for. A bare `<a>` carries no marker, so no rule in the sheet can reach
 * it — which is why the shell's nav links and the breadcrumb trail each needed a selector of
 * their own, and why a link in a module's prose had no treatment at all. And an in-app
 * `<a href="/…">` bypasses the router: a full reload, and the role-aware guard never runs. The
 * boundary lint refuses that anchor in module code; this is the thing to use instead.
 *
 * Outside a Terp router it degrades to a plain anchor, like every other layout component that
 * renders a link, so it still works in a story or a test tree.
 *
 * An external destination opened in a new tab gets `rel="noreferrer"` — without it the opened
 * page can reach back through `window.opener`, which is the reverse-tabnabbing shape the
 * boundary lint's own `no-unsafe-target-blank` rule exists for.
 */
export function Link({ to, newTab = false, children, ...rest }: LinkProps) {
  const navLink = useNavLink();
  assertRoutable(to);
  if (isInApp(to) && navLink !== null) {
    // Two destinations for two kinds of attribute, and the split is deliberate.
    //
    // The caller's own attributes go to the ANCHOR through the renderer's `attributes`, because
    // that is the only place they mean anything: an `aria-label` on a wrapper is ignored, so it
    // would be silently dropped for an in-app path and honoured for an external one — the same
    // prop behaving differently depending on whether the destination starts with a slash.
    //
    // The MARKER stays on the wrapper, which is `HubCard`'s pattern. It could travel through
    // `attributes` too, and must not: an app supplying its own renderer that destructures only
    // `{ to, children }` is source-compatible and forwards nothing, and the failure would be an
    // unstyled link with no error. A component's own styling hook cannot depend on a caller
    // honouring a seam. The `<span>` is inline, so it adds no box to a line of prose.
    return (
      <span data-terp="link">{navLink({ to, children, attributes: rest })}</span>
    );
  }
  const external = !isInApp(to) && newTab;
  return (
    <a
      {...rest}
      data-terp="link"
      href={to}
      target={external ? "_blank" : undefined}
      rel={external ? "noreferrer" : undefined}
    >
      {children}
    </a>
  );
}
