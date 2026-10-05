import { useEffect } from "react";
import type { RefObject } from "react";

/**
 * Keeps a scrolling strip's current item in the strip's view: the strip scrolls, the page never
 * does. Tab strips are one line that scrolls sideways where they do not fit (the sheet's Tabs and
 * Module navigation notes), so a current tab can sit past the strip's edge, as the third of three
 * on a phone does; this brings it back whenever the current item changes.
 *
 * Measured rather than delegated to `scrollIntoView`, which scrolls every scrollable ancestor up
 * to the page. Where nothing is laid out (jsdom, a strip that fits) the boxes agree and it does
 * nothing.
 */
export function useCurrentInView(
  strip: RefObject<HTMLElement | null>,
  current: string | undefined,
  selector: string,
): void {
  useEffect(() => {
    const list = strip.current;
    const item = list?.querySelector<HTMLElement>(selector);
    if (!list || !item) return;
    const bounds = list.getBoundingClientRect();
    const box = item.getBoundingClientRect();
    if (box.left < bounds.left) list.scrollLeft -= bounds.left - box.left;
    else if (box.right > bounds.right) list.scrollLeft += box.right - bounds.right;
  }, [strip, current, selector]);
}
