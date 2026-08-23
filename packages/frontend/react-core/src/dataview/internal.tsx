import { createContext, useCallback, useContext } from "react";
import type { ReactNode } from "react";

import { useFormatDate } from "../format";
import { injectTerpStyles } from "../styles";
import { Menu, MenuItem } from "../ui/Menu";
import { useUiText } from "../uiText";
import type { ResolveUiText, UiText } from "../uiText";
import { DEFAULT_DATA_VIEW_STRINGS, formatDataViewString } from "./types";
import type { DataViewStrings } from "./types";

injectTerpStyles();

/** Internal: merged strings + resolver every DataView sub-component reads. */
export interface DataViewTextApi {
  strings: DataViewStrings;
  resolve: ResolveUiText;
  /** Resolve a countable string and fill its `{placeholder}`s. */
  format: (text: UiText, values: Record<string, string | number>) => string;
}

const DataViewTextContext = createContext<DataViewTextApi>({
  strings: DEFAULT_DATA_VIEW_STRINGS,
  resolve: (text) => (typeof text === "string" ? text : text.message),
  format: (text, values) =>
    formatDataViewString(typeof text === "string" ? text : text.message, values),
});

export function useDataViewText(): DataViewTextApi {
  return useContext(DataViewTextContext);
}

/**
 * Stringify a cell for a column that declares no `cell` renderer.
 *
 * One hook rather than a helper per renderer, because there WERE two: the table had a private
 * `formatCell` and the mobile card list inlined the same three lines. They agreed, so nothing
 * caught that they were two, and the first change to either would have made a row render one way
 * on a desktop and another on a phone.
 *
 * The `Date` branch is why that mattered. `accessor` returns `unknown`, so a `Date` is type-legal
 * and `String(value)` renders `Wed Aug 21 2026 00:00:00 GMT+0200 (Central European Summer Time)`
 * in a table cell. Nothing in this tree returns one today, which is exactly why it was worth
 * closing now rather than after an app discovered it.
 */
export function useCellFormatter(): (value: unknown) => ReactNode {
  const formatDate = useFormatDate();
  return useCallback(
    (value: unknown) => {
      if (value === null || value === undefined) {
        return null;
      }
      if (value instanceof Date) {
        return formatDate(value);
      }
      return String(value);
    },
    [formatDate],
  );
}

export function DataViewTextProvider({
  overrides,
  children,
}: {
  overrides?: Partial<DataViewStrings>;
  children: ReactNode;
}) {
  const resolve = useUiText();
  const strings: DataViewStrings = { ...DEFAULT_DATA_VIEW_STRINGS, ...overrides };
  const api: DataViewTextApi = {
    strings,
    resolve,
    format: (text, values) => formatDataViewString(resolve(text), values),
  };
  return <DataViewTextContext.Provider value={api}>{children}</DataViewTextContext.Provider>;
}

/**
 * Internal DataView wrapper over the shared react-core Menu primitive.
 */
export function DataViewMenu({
  trigger,
  triggerLabel,
  align = "end",
  defaultOpen,
  children,
}: {
  /** Trigger content (an icon or a label). */
  trigger: ReactNode;
  /** Accessible name of the trigger button. */
  triggerLabel: string;
  align?: "start" | "end";
  /** Open on mount — threaded to `Menu`, which has carried this since the overlays moved. */
  defaultOpen?: boolean;
  /** Panel content; render-prop so items can close the menu after acting. */
  children: (close: () => void) => ReactNode;
}) {
  return (
    <Menu trigger={trigger} triggerLabel={triggerLabel} align={align} defaultOpen={defaultOpen}>
      {({ close }) => children(() => close(false))}
    </Menu>
  );
}

/** Internal: one item inside a {@link DataViewMenu}. */
export function DataViewMenuItem({
  label,
  destructive = false,
  disabled = false,
  selected,
  icon,
  onSelect,
}: {
  label: string;
  destructive?: boolean;
  disabled?: boolean;
  /** Marks one choice in a mutually exclusive menu (renders `menuitemradio`). */
  selected?: boolean;
  icon?: ReactNode;
  onSelect: () => void;
}) {
  return (
    <MenuItem
      label={label}
      icon={icon}
      selected={selected}
      destructive={destructive}
      disabled={disabled}
      onSelect={onSelect}
    />
  );
}
