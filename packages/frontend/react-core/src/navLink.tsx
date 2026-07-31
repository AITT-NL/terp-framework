import { createContext, useContext } from "react";
import type { ReactNode } from "react";

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
export type NavLinkRenderer = (props: { to: string; children: ReactNode }) => ReactNode;

export const NavLinkContext = createContext<NavLinkRenderer | null>(null);

/**
 * The ambient link renderer, or `null` outside a Terp router. Callers fall back to a
 * plain anchor — never silently, always as the documented last resort.
 */
export function useNavLink(): NavLinkRenderer | null {
  return useContext(NavLinkContext);
}
