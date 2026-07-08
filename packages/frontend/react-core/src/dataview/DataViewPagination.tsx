import type { CSSProperties } from "react";

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

const pagerButtonStyle = (disabled: boolean): CSSProperties => ({
  display: "inline-flex",
  alignItems: "center",
  minHeight: "2rem",
  padding: "var(--space-1) var(--space-2)",
  background: "var(--color-neutral-0)",
  border: "1px solid var(--color-neutral-300)",
  borderRadius: "var(--radius-md)",
  cursor: disabled ? "not-allowed" : "pointer",
  color: disabled ? "var(--color-neutral-300)" : "var(--color-neutral-700)",
});

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
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: "var(--space-3)",
        flexWrap: "wrap",
        padding: "var(--space-2) var(--space-3)",
        borderTop: "1px solid var(--color-neutral-200)",
        fontSize: "var(--font-size-sm)",
        color: "var(--color-neutral-500)",
      }}
    >
      <span>{format(strings.resultsRange, { from, to, total: totalCount })}</span>
      {pageCount > 1 && (
        <span style={{ display: "inline-flex", alignItems: "center", gap: "var(--space-2)" }}>
          <span>{format(strings.pageOf, { page: pageIndex + 1, pages: pageCount })}</span>
          <button
            type="button"
            aria-label={format(strings.firstPage, {})}
            disabled={atFirst}
            onClick={() => goTo(0)}
            data-terp="iconbutton"
            style={pagerButtonStyle(atFirst)}
          >
            <PageFirstGlyph />
          </button>
          <button
            type="button"
            aria-label={format(strings.previousPage, {})}
            disabled={atFirst}
            onClick={() => goTo(pageIndex - 1)}
            data-terp="iconbutton"
            style={pagerButtonStyle(atFirst)}
          >
            <PagePrevGlyph />
          </button>
          <button
            type="button"
            aria-label={format(strings.nextPage, {})}
            disabled={atLast}
            onClick={() => goTo(pageIndex + 1)}
            data-terp="iconbutton"
            style={pagerButtonStyle(atLast)}
          >
            <PageNextGlyph />
          </button>
          <button
            type="button"
            aria-label={format(strings.lastPage, {})}
            disabled={atLast}
            onClick={() => goTo(pageCount - 1)}
            data-terp="iconbutton"
            style={pagerButtonStyle(atLast)}
          >
            <PageLastGlyph />
          </button>
        </span>
      )}
    </div>
  );
}
