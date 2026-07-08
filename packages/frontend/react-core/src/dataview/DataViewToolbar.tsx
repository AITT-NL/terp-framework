import type { ReactNode } from "react";

import { Button } from "../ui/Button";
import { Input } from "../ui/Input";
import { Select } from "../ui/Select";
import { DataViewColumnSettings } from "./DataViewColumnSettings";
import type { DataViewColumnSettingsProps } from "./DataViewColumnSettings";
import { CardsGlyph, CloseGlyph, EllipsisGlyph, SearchGlyph, TableGlyph } from "./glyphs";
import { DataViewMenu, DataViewMenuItem, useDataViewText } from "./internal";
import { useViewSearch } from "./hooks/useViewSearch";
import type { DataViewBatchAction, DataViewSearchScope } from "./types";
import type { UiText } from "../uiText";

export interface DataViewToolbarProps<T> {
  // Search
  searchEnabled: boolean;
  search: string;
  onSearchChange: (search: string) => void;
  searchPlaceholder?: UiText;
  searchDebounceMs?: number;
  searchScope?: DataViewSearchScope;
  onClearFilters?: () => void;
  hasActiveFilters: boolean;

  // View controls
  columnSettings?: DataViewColumnSettingsProps<T>;
  layout: "table" | "cards";
  onLayoutChange?: (layout: "table" | "cards") => void;
  pageSize?: number;
  pageSizeOptions?: number[];
  onPageSizeChange?: (pageSize: number) => void;

  // Selection mode
  selectedCount: number;
  totalCount: number;
  selectAllAcrossPages: boolean;
  onSelectAllAcrossPages?: () => void;
  onClearSelection: () => void;
  batchActions?: DataViewBatchAction<T>[];
  onBatchAction: (action: DataViewBatchAction<T>) => void;

  isFetching: boolean;
  /** Custom filter controls. */
  children?: ReactNode;
  trailing?: ReactNode;
}

/**
 * The DataView toolbar. In its normal mode it hosts search, caller filter controls,
 * the page-size selector, the table/cards toggle and the column-settings menu; when
 * rows are selected it switches to selection mode ("N selected", batch actions,
 * select-all-across-pages, clear selection).
 */
export function DataViewToolbar<T>(props: DataViewToolbarProps<T>) {
  const { strings, resolve, format } = useDataViewText();
  const search = useViewSearch(props.search, props.onSearchChange, props.searchDebounceMs ?? 0);

  const selectionMode = props.selectedCount > 0;

  const barStyle = {
    display: "flex",
    alignItems: "center",
    gap: "var(--space-2)",
    flexWrap: "wrap",
    padding: "var(--space-2) var(--space-3)",
    borderBottom: "1px solid var(--color-neutral-200)",
    background: selectionMode ? "var(--color-neutral-50)" : "var(--color-neutral-0)",
    borderTopLeftRadius: "var(--radius-lg)",
    borderTopRightRadius: "var(--radius-lg)",
    minHeight: "3rem",
  } as const;

  if (selectionMode) {
    const inlineActions = (props.batchActions ?? []).filter((action) => action.inline !== false);
    const overflowActions = (props.batchActions ?? []).filter((action) => action.inline === false);
    return (
      <div style={barStyle}>
        <span style={{ fontWeight: "var(--font-weight-medium)" as never }}>
          {format(strings.selected, { count: props.selectedCount })}
        </span>
        {props.onSelectAllAcrossPages !== undefined && !props.selectAllAcrossPages && (
          <Button variant="secondary" onClick={props.onSelectAllAcrossPages}>
            {format(strings.selectAllResults, { total: props.totalCount })}
          </Button>
        )}
        <span style={{ display: "inline-flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
          {inlineActions.map((action, index) => (
            <Button
              key={index}
              variant={action.variant === "destructive" ? "danger" : "secondary"}
              onClick={() => props.onBatchAction(action)}
            >
              {action.icon !== undefined && (
                <span aria-hidden style={{ display: "inline-flex", marginRight: "var(--space-1)" }}>
                  {action.icon}
                </span>
              )}
              {resolve(action.label)}
            </Button>
          ))}
          {overflowActions.length > 0 && (
            <DataViewMenu trigger={<EllipsisGlyph />} triggerLabel={resolve(strings.moreActions)}>
              {(close) => (
                <>
                  {overflowActions.map((action, index) => (
                    <DataViewMenuItem
                      key={index}
                      label={resolve(action.label)}
                      icon={action.icon}
                      destructive={action.variant === "destructive"}
                      onSelect={() => {
                        close();
                        props.onBatchAction(action);
                      }}
                    />
                  ))}
                </>
              )}
            </DataViewMenu>
          )}
        </span>
        <span style={{ flex: 1 }} />
        <Button variant="secondary" onClick={props.onClearSelection}>
          {resolve(strings.clearSelection)}
        </Button>
      </div>
    );
  }

  return (
    <div style={barStyle}>
      {props.searchEnabled && (
        <span style={{ position: "relative", display: "inline-flex", alignItems: "center" }}>
          <span
            aria-hidden
            style={{
              position: "absolute",
              left: "var(--space-2)",
              display: "inline-flex",
              color: "var(--color-neutral-500)",
              pointerEvents: "none",
            }}
          >
            <SearchGlyph size={14} />
          </span>
          <Input
            type="search"
            value={search.inputValue}
            onChange={(event) => search.setInputValue(event.target.value)}
            placeholder={resolve(props.searchPlaceholder ?? strings.searchPlaceholder)}
            aria-label={resolve(props.searchPlaceholder ?? strings.searchPlaceholder)}
            style={{
              paddingLeft: "var(--space-6)",
              paddingRight: "var(--space-6)",
              width: "16rem",
              maxWidth: "100%",
            }}
          />
          {search.inputValue !== "" && (
            <button
              type="button"
              aria-label={resolve(strings.clearSearch)}
              onClick={search.clear}
              style={{
                position: "absolute",
                right: "var(--space-1)",
                display: "inline-flex",
                padding: "var(--space-1)",
                background: "transparent",
                border: "none",
                cursor: "pointer",
                color: "var(--color-neutral-500)",
              }}
            >
              <CloseGlyph size={14} />
            </button>
          )}
        </span>
      )}
      {props.searchScope !== undefined && props.search.trim() !== "" && (
        <Button
          variant="secondary"
          aria-pressed={props.searchScope.broadened}
          onClick={() => props.searchScope?.onBroadenedChange(!props.searchScope.broadened)}
        >
          {resolve(
            props.searchScope.broadened ? props.searchScope.broadenedLabel : props.searchScope.label,
          )}
        </Button>
      )}
      {props.children}
      {props.onClearFilters !== undefined && props.hasActiveFilters && (
        <Button variant="secondary" onClick={props.onClearFilters}>
          {resolve(strings.clearFilters)}
        </Button>
      )}
      {props.isFetching && (
        <span
          role="status"
          style={{ fontSize: "var(--font-size-sm)", color: "var(--color-neutral-500)" }}
        >
          {resolve(strings.refreshing)}
        </span>
      )}
      <span style={{ flex: 1 }} />
      {props.onPageSizeChange !== undefined && props.pageSize !== undefined && (
        <Select
          value={String(props.pageSize)}
          aria-label={resolve(strings.pageSize)}
          onChange={(event) => props.onPageSizeChange?.(Number(event.target.value))}
        >
          {(props.pageSizeOptions ?? [10, 25, 50, 100]).map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </Select>
      )}
      {props.onLayoutChange !== undefined && (
        <span style={{ display: "inline-flex", gap: "var(--space-1)" }}>
          <button
            type="button"
            aria-label={resolve(strings.tableView)}
            aria-pressed={props.layout === "table"}
            onClick={() => props.onLayoutChange?.("table")}
            style={layoutToggleStyle(props.layout === "table")}
          >
            <TableGlyph />
          </button>
          <button
            type="button"
            aria-label={resolve(strings.cardView)}
            aria-pressed={props.layout === "cards"}
            onClick={() => props.onLayoutChange?.("cards")}
            style={layoutToggleStyle(props.layout === "cards")}
          >
            <CardsGlyph />
          </button>
        </span>
      )}
      {props.columnSettings !== undefined && <DataViewColumnSettings {...props.columnSettings} />}
      {props.trailing}
    </div>
  );
}

function layoutToggleStyle(active: boolean) {
  return {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    minHeight: "2rem",
    padding: "var(--space-1) var(--space-2)",
    background: active ? "var(--color-neutral-100)" : "transparent",
    border: "1px solid var(--color-neutral-300)",
    borderRadius: "var(--radius-md)",
    cursor: "pointer",
    color: active ? "var(--color-neutral-900)" : "var(--color-neutral-500)",
  } as const;
}
