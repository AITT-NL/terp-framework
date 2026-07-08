// The DataView family — the single sanctioned surface for rendering data collections.
// See ./README.md for usage.
export { DataView } from "./DataView";
export type { DataViewProps } from "./DataView";
export { DataViewToolbar } from "./DataViewToolbar";
export type { DataViewToolbarProps } from "./DataViewToolbar";
export { DataViewPagination } from "./DataViewPagination";
export type { DataViewPaginationProps } from "./DataViewPagination";
export { DataViewColumnSettings } from "./DataViewColumnSettings";
export type { DataViewColumnSettingsProps } from "./DataViewColumnSettings";
export { DataViewRowActions } from "./DataViewRowActions";
export type { DataViewRowActionsLayout, DataViewRowActionsProps } from "./DataViewRowActions";
export { DataViewExpandableRow, DataViewExpandToggle } from "./DataViewExpandableRow";
export { DataViewCardList } from "./DataViewCardList";
export type { DataViewCardListProps } from "./DataViewCardList";
export { DataViewTable } from "./DataViewTable";
export type { DataViewTableProps } from "./DataViewTable";

export type {
  DataViewQuery,
  DataViewResult,
  DataViewRepository,
  DataViewState,
  ViewStateRepository,
  DataViewColumn,
  DataViewColumnMeta,
  DataViewMobileSlot,
  DataViewRowAction,
  DataViewBatchAction,
  DataViewSearchScope,
  DataViewStrings,
} from "./types";
export { DEFAULT_DATA_VIEW_STRINGS, emptyDataViewState } from "./types";

export { InMemoryDataViewRepository } from "./repositories/InMemoryDataViewRepository";
export type { InMemoryDataViewRepositoryOptions } from "./repositories/InMemoryDataViewRepository";
export { HttpDataViewRepository } from "./repositories/HttpDataViewRepository";
export type {
  HttpDataViewParams,
  HttpDataViewRepositoryOptions,
  HttpRequestAdapter,
} from "./repositories/HttpDataViewRepository";
export {
  InMemoryViewStateRepository,
  LocalStorageViewStateRepository,
} from "./repositories/viewState";

export { useDataViewState } from "./hooks/useDataViewState";
export type {
  DataViewControlledQuery,
  DataViewFilters,
  DataViewPaginationState,
  DataViewSorting,
  UseDataViewStateOptions,
  UseDataViewStateResult,
} from "./hooks/useDataViewState";
export { useServerDataView } from "./hooks/useServerDataView";
export type { UseServerDataViewOptions } from "./hooks/useServerDataView";
export { useViewSearch } from "./hooks/useViewSearch";
export type { UseViewSearchResult } from "./hooks/useViewSearch";
export { useDataViewQuery } from "./hooks/useDataViewQuery";
export type { UseDataViewQueryResult } from "./hooks/useDataViewQuery";
