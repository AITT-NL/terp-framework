import { createContext, useContext } from "react";
import type { AnchorHTMLAttributes, ReactNode } from "react";

/**
 * How the surrounding router renders an in-app link.
 *
 * The layout components (`Breadcrumbs`, `HubCard`) are deliberately router-agnostic and
 * take a `renderLink` prop — but their *default* used to be a raw `<a href>`, which is
 * the one construct the boundary lint refuses in app code, and which does a full page
 * reload instead of a client-side navigation. Forgetting the prop therefore produced a
 * silently degraded app: no error, no lint hit (the anchor lives inside react-core), just
 * a white flash on every crumb click.
 *
 * So `buildAppRouter` publishes the router's own `Link` here, and the components default
 * to it. The anchor remains only for a component rendered outside any Terp router (a
 * standalone story or unit test), where there is no router to navigate with.
 */
export type NavLinkRenderer = (props: {
  to: string;
  children: ReactNode;
  /**
   * HTML attributes for the rendered anchor **itself**, rather than for a wrapper around it.
   *
   * Added because the alternative was a silent loss. A caller's `aria-label` or `id` has to
   * land on the anchor to mean anything — an `aria-label` on a `<span>` wrapping a link is
   * ignored, so the link keeps its content as its accessible name and the caller's intent
   * disappears with no error. `Link` hit exactly that: it renders through this seam for an
   * in-app path and as a plain anchor otherwise, so the same prop worked in one branch and
   * was dropped in the other, decided by whether the destination happened to start with `/`.
   *
   * An implementation that destructures only `{ to, children }` stays source-compatible and
   * simply forwards nothing — which is why the marker a component styles itself by is NOT
   * passed this way. That stays on a wrapper the component owns, so a renderer cannot lose it.
   */
  attributes?: Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href">;
}) => ReactNode;

export const NavLinkContext = createContext<NavLinkRenderer | null>(null);

/**
 * The ambient link renderer, or `null` outside a Terp router. Callers fall back to a
 * plain anchor — never silently, always as the documented last resort.
 */
export function useNavLink(): NavLinkRenderer | null {
  return useContext(NavLinkContext);
}
