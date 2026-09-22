import { useDataViewText } from "./internal";
import {
  PageFirstGlyph,
  PageLastGlyph,
  PageNextGlyph,
  PagePrevGlyph,
} from "./glyphs";
import type { DataViewPaginationState } from "./hooks/useDataViewState";

export interface DataViewPaginationProps {
  pagination: DataViewPaginationState;
  /** How many rows match, or `undefined` while that is not known yet. */
  totalCount: number | undefined;
  onPaginationChange: (pagination: DataViewPaginationState) => void;
}

/**
 * The footer pagination bar: "X-Y of Z results", the current page / page count, and
 * first / prev / next / last controls (disabled at bounds; page controls hidden when
 * there is only one page).
 *
 * **An unknown total renders as nothing, never as zero.** The bar used to compute its
 * range from a `totalCount` that was `0` until the first query answered, so a fresh view
 * asserted "0-0 of 0 results" underneath its own loading skeleton -- a count stated with
 * authority, next to a placeholder admitting there is no data yet, and wrong as often as
 * not. `useResource` drew this distinction in 0.17.0 ("unknown is a real answer and must
 * not render as zero"); this is the same one, one component over. The bar keeps its box
 * either way, so nothing moves when the number arrives.
 */
export function DataViewPagination({
  pagination,
  totalCount,
  onPaginationChange,
}: DataViewPaginationProps) {
  const { strings, format } = useDataViewText();

  const known = totalCount !== undefined;
  const pageCount = Math.max(1, Math.ceil((totalCount ?? 0) / pagination.pageSize));
  const pageIndex = Math.min(pagination.pageIndex, pageCount - 1);
  const from = !known || totalCount === 0 ? 0 : pageIndex * pagination.pageSize + 1;
  const to = Math.min(totalCount ?? 0, (pageIndex + 1) * pagination.pageSize);

  const goTo = (index: number) => onPaginationChange({ ...pagination, pageIndex: index });
  const atFirst = pageIndex === 0;
  const atLast = pageIndex >= pageCount - 1;

  return (
    <div data-terp="dataview-pagination">
      <span>{known ? format(strings.resultsRange, { from, to, total: totalCount }) : null}</span>
      {/* aria-disabled, not disabled, and the difference is where focus goes. Each of these
          four buttons has a bound condition recomputed from what its own click just changed, so
          pressing "next" until the last page disabled the very control the user was operating —
          and a disabled element cannot hold focus, so the browser dropped it to <body>. A
          keyboard user paging to the end lost their place in the document at the exact moment
          they arrived. Kept focusable and announced as disabled instead, with the handler inert
          on the bound; the sheet paints [aria-disabled="true"] identically to :disabled. */}
      {known && pageCount > 1 && (
        <span data-terp="dataview-pager">
          <span>{format(strings.pageOf, { page: pageIndex + 1, pages: pageCount })}</span>
          <button
            type="button"
            aria-label={format(strings.firstPage, {})}
            aria-disabled={atFirst || undefined}
            onClick={() => (atFirst ? undefined : goTo(0))}
            data-terp="iconbutton"
          >
            <PageFirstGlyph />
          </button>
          <button
            type="button"
            aria-label={format(strings.previousPage, {})}
            aria-disabled={atFirst || undefined}
            onClick={() => (atFirst ? undefined : goTo(pageIndex - 1))}
            data-terp="iconbutton"
          >
            <PagePrevGlyph />
          </button>
          <button
            type="button"
            aria-label={format(strings.nextPage, {})}
            aria-disabled={atLast || undefined}
            onClick={() => (atLast ? undefined : goTo(pageIndex + 1))}
            data-terp="iconbutton"
          >
            <PageNextGlyph />
          </button>
          <button
            type="button"
            aria-label={format(strings.lastPage, {})}
            aria-disabled={atLast || undefined}
            onClick={() => (atLast ? undefined : goTo(pageCount - 1))}
            data-terp="iconbutton"
          >
            <PageLastGlyph />
          </button>
        </span>
      )}
    </div>
  );
}
