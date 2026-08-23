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
  totalCount: number;
  onPaginationChange: (pagination: DataViewPaginationState) => void;
}

/**
 * The footer pagination bar: "X–Y of Z results", the current page / page count, and
 * first / prev / next / last controls (disabled at bounds; page controls hidden when
 * there is only one page).
 */
export function DataViewPagination({
  pagination,
  totalCount,
  onPaginationChange,
}: DataViewPaginationProps) {
  const { strings, format } = useDataViewText();

  const pageCount = Math.max(1, Math.ceil(totalCount / pagination.pageSize));
  const pageIndex = Math.min(pagination.pageIndex, pageCount - 1);
  const from = totalCount === 0 ? 0 : pageIndex * pagination.pageSize + 1;
  const to = Math.min(totalCount, (pageIndex + 1) * pagination.pageSize);

  const goTo = (index: number) => onPaginationChange({ ...pagination, pageIndex: index });
  const atFirst = pageIndex === 0;
  const atLast = pageIndex >= pageCount - 1;

  return (
    <div data-terp="dataview-pagination">
      <span>{format(strings.resultsRange, { from, to, total: totalCount })}</span>
      {/* aria-disabled, not disabled, and the difference is where focus goes. Each of these
          four buttons has a bound condition recomputed from what its own click just changed, so
          pressing "next" until the last page disabled the very control the user was operating —
          and a disabled element cannot hold focus, so the browser dropped it to <body>. A
          keyboard user paging to the end lost their place in the document at the exact moment
          they arrived. Kept focusable and announced as disabled instead, with the handler inert
          on the bound; the sheet paints [aria-disabled="true"] identically to :disabled. */}
      {pageCount > 1 && (
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
