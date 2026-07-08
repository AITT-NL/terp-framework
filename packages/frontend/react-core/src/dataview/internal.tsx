import { createContext, useContext } from "react";
import type { ReactNode } from "react";

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
  children,
}: {
  /** Trigger content (an icon or a label). */
  trigger: ReactNode;
  /** Accessible name of the trigger button. */
  triggerLabel: string;
  align?: "start" | "end";
  /** Panel content; render-prop so items can close the menu after acting. */
  children: (close: () => void) => ReactNode;
}) {
  return (
    <Menu trigger={trigger} triggerLabel={triggerLabel} align={align}>
      {({ close }) => children(() => close(false))}
    </Menu>
  );
}

/** Internal: one item inside a {@link DataViewMenu}. */
export function DataViewMenuItem({
  label,
  destructive = false,
  disabled = false,
  icon,
  onSelect,
}: {
  label: string;
  destructive?: boolean;
  disabled?: boolean;
  icon?: ReactNode;
  onSelect: () => void;
}) {
  return (
    <MenuItem
      label={label}
      icon={icon}
      destructive={destructive}
      disabled={disabled}
      onSelect={onSelect}
    />
  );
}
