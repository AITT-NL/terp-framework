import { createContext, useContext } from "react";

/**
 * The runtime half of the "every routed view is a page archetype" control. The router's route
 * wrapper provides a marker callback; {@link Page} (which `OverviewPage` / `DetailPage` /
 * `HubPage` all compose) invokes it during render. After mount the wrapper checks the mark and
 * fails closed on a routed view that skipped the archetypes — so every screen keeps the frame
 * (breadcrumbs, one `h1`, the loading/error slots) even if a lint were bypassed.
 */
export const PageMarkerContext = createContext<(() => void) | null>(null);

/** The marker callback for the current routed view, or null outside a routed view. */
export function usePageMarker(): (() => void) | null {
  return useContext(PageMarkerContext);
}
