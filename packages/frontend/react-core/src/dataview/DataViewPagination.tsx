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
      {pageCount > 1 && (
        <span data-terp="dataview-pager">
          <span>{format(strings.pageOf, { page: pageIndex + 1, pages: pageCount })}</span>
          <button
            type="button"
            aria-label={format(strings.firstPage, {})}
            disabled={atFirst}
            onClick={() => goTo(0)}
            data-terp="iconbutton"
          >
            <PageFirstGlyph />
          </button>
          <button
            type="button"
            aria-label={format(strings.previousPage, {})}
            disabled={atFirst}
            onClick={() => goTo(pageIndex - 1)}
            data-terp="iconbutton"
          >
            <PagePrevGlyph />
          </button>
          <button
            type="button"
            aria-label={format(strings.nextPage, {})}
            disabled={atLast}
            onClick={() => goTo(pageIndex + 1)}
            data-terp="iconbutton"
          >
            <PageNextGlyph />
          </button>
          <button
            type="button"
            aria-label={format(strings.lastPage, {})}
            disabled={atLast}
            onClick={() => goTo(pageCount - 1)}
            data-terp="iconbutton"
          >
            <PageLastGlyph />
          </button>
        </span>
      )}
    </div>
  );
}
