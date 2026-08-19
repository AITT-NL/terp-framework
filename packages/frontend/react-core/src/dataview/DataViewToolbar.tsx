import type { ReactNode } from "react";

import { Button } from "../ui/Button";
import { Input } from "../ui/Input";
import { DataViewColumnSettings } from "./DataViewColumnSettings";
import type { DataViewColumnSettingsProps } from "./DataViewColumnSettings";
import { CardsGlyph, ChevronDownGlyph, CloseGlyph, EllipsisGlyph, SearchGlyph, TableGlyph } from "./glyphs";
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
 *
 * It renders no inline styles: the band, both its modes and every part inside it take
 * their geometry from the injected react-core sheet, matched on the `data-terp` markers
 * stamped below and on `data-variant="selection"` (ADR 0094). Two of this element's
 * direct children are arbitrary caller slots — `children` and `trailing` — which is why
 * the band's own rule declares no `color` and why the refresh status carries a marker
 * instead of being reached as `[data-terp="dataview-toolbar"] > [role="status"]`: owning
 * one instance of an attribute is not owning every element such a selector reaches.
 */
export function DataViewToolbar<T>(props: DataViewToolbarProps<T>) {
  const { strings, resolve, format } = useDataViewText();
  const search = useViewSearch(props.search, props.onSearchChange, props.searchDebounceMs ?? 0);

  const selectionMode = props.selectedCount > 0;

  if (selectionMode) {
    const inlineActions = (props.batchActions ?? []).filter((action) => action.inline !== false);
    const overflowActions = (props.batchActions ?? []).filter((action) => action.inline === false);
    return (
      // data-variant rather than data-selected: in this cluster "selected" already means
      // "this element is selected" (rows, cards, menu items), and the toolbar is not
      // selected — it is showing a different mode. Stamped as a literal in this branch and
      // omitted in the other, which is the cluster's idiom of not naming the default.
      <div data-terp="dataview-toolbar" data-variant="selection">
        <span data-terp="dataview-toolbar-count">
          {format(strings.selected, { count: props.selectedCount })}
        </span>
        {props.onSelectAllAcrossPages !== undefined && !props.selectAllAcrossPages && (
          <Button variant="secondary" onClick={props.onSelectAllAcrossPages}>
            {format(strings.selectAllResults, { total: props.totalCount })}
          </Button>
        )}
        <span data-terp="dataview-toolbar-actions">
          {inlineActions.map((action, index) => (
            <Button
              key={index}
              variant={action.variant === "destructive" ? "danger" : "secondary"}
              // Button's own icon slot, rather than a hand-rolled aria-hidden span: it
              // renders [data-terp="button-icon"], which is already ruled and already
              // carries flex-shrink: 0 that the hand-rolled one lacked.
              icon={action.icon}
              onClick={() => props.onBatchAction(action)}
            >
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
        <span data-terp="dataview-toolbar-spacer" />
        <Button variant="secondary" onClick={props.onClearSelection}>
          {resolve(strings.clearSelection)}
        </Button>
      </div>
    );
  }

  return (
    <div data-terp="dataview-toolbar">
      {props.searchEnabled && (
        <span data-terp="dataview-toolbar-search">
          {/* Unmarked, and reached as this wrapper's only span child: it is decoration with
              no state, and the wrapper holds no caller slot. */}
          <span aria-hidden>
            <SearchGlyph size={14} />
          </span>
          <Input
            type="search"
            value={search.inputValue}
            onChange={(event) => search.setInputValue(event.target.value)}
            placeholder={resolve(props.searchPlaceholder ?? strings.searchPlaceholder)}
            aria-label={resolve(props.searchPlaceholder ?? strings.searchPlaceholder)}
          />
          {search.inputValue !== "" && (
            <button
              type="button"
              data-terp="iconbutton"
              aria-label={resolve(strings.clearSearch)}
              onClick={search.clear}
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
        <span role="status" data-terp="dataview-toolbar-status">
          {resolve(strings.refreshing)}
        </span>
      )}
      <span data-terp="dataview-toolbar-spacer" />
      {props.onPageSizeChange !== undefined && props.pageSize !== undefined && (
        <DataViewMenu
          triggerLabel={resolve(strings.pageSize)}
          // A fragment, not a wrapper span: [data-terp="menu-trigger"] already declares
          // display: inline-flex, align-items: center, justify-content: center and
          // gap: var(--space-1) — the deleted span's three declarations verbatim, with the
          // gap applying to exactly this pair. Keeping the span would need a marker of its
          // own, because [data-terp="menu-trigger"] > span would also catch the
          // column-settings trigger's text span in this same toolbar.
          trigger={
            <>
              {props.pageSize}
              <ChevronDownGlyph size={14} />
            </>
          }
        >
          {(close) =>
            (props.pageSizeOptions ?? [10, 25, 50, 100]).map((option) => (
              <DataViewMenuItem
                key={option}
                label={String(option)}
                selected={option === props.pageSize}
                onSelect={() => {
                  props.onPageSizeChange?.(option);
                  close();
                }}
              />
            ))
          }
        </DataViewMenu>
      )}
      {props.onLayoutChange !== undefined && (
        <span data-terp="dataview-toolbar-layout">
          {/* The shared icon-button marker, so these two gain the transition, the focus
              ring and reduced-motion coverage they escaped entirely. Which one is active is
              aria-pressed — the real ARIA state, not a data attribute duplicating it — and
              this component is its sole author, setting it from its own layout prop. */}
          <button
            type="button"
            data-terp="iconbutton"
            aria-label={resolve(strings.tableView)}
            aria-pressed={props.layout === "table"}
            onClick={() => props.onLayoutChange?.("table")}
          >
            <TableGlyph />
          </button>
          <button
            type="button"
            data-terp="iconbutton"
            aria-label={resolve(strings.cardView)}
            aria-pressed={props.layout === "cards"}
            onClick={() => props.onLayoutChange?.("cards")}
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
