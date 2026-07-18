import { useId, useMemo, useState } from "react";
import type { CSSProperties, KeyboardEvent, ReactNode } from "react";

import { injectTerpStyles } from "../styles";
import { useUiText } from "../uiText";
import type { UiText } from "../uiText";
import { CONTROL_TEXT_STYLE } from "./controlStyles";

injectTerpStyles();

const rootStyle: CSSProperties = { display: "grid", gap: "var(--space-3)" };
const tabListStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: "var(--space-1)",
  borderBlockEnd: "1px solid var(--color-neutral-200)",
};
const tabStyle = (selected: boolean): CSSProperties => ({
  ...CONTROL_TEXT_STYLE,
  fontWeight: (selected
    ? "var(--font-weight-semibold)"
    : "var(--font-weight-medium)") as never,
  padding: "var(--space-2) var(--space-3)",
  border: 0,
  borderBlockEnd: selected ? "2px solid var(--color-brand-primary)" : "2px solid transparent",
  color: selected ? "var(--color-brand-primary)" : "var(--color-neutral-600)",
  background: "transparent",
  cursor: "pointer",
  marginBlockEnd: "-1px",
});
const panelStyle: CSSProperties = { color: "var(--color-neutral-900)" };

export interface TabItem {
  value: string;
  label: UiText;
  content: ReactNode;
  disabled?: boolean;
}

export interface TabsProps {
  tabs: readonly TabItem[];
  value?: string;
  defaultValue?: string;
  onChange?: (value: string) => void;
  label?: UiText;
}

/** In-page tab set with controlled/uncontrolled selection and arrow-key navigation. */
export function Tabs({ tabs, value, defaultValue, onChange, label }: TabsProps) {
  const baseId = useId();
  const resolve = useUiText();
  const enabledTabs = useMemo(() => tabs.filter((tab) => !tab.disabled), [tabs]);
  const firstValue = enabledTabs[0]?.value ?? tabs[0]?.value ?? "";
  const [uncontrolledValue, setUncontrolledValue] = useState(defaultValue ?? firstValue);
  const selectedValue = value ?? uncontrolledValue;
  const selectedTab = tabs.find((tab) => tab.value === selectedValue) ?? enabledTabs[0] ?? tabs[0];

  function select(next: string) {
    if (value === undefined) {
      setUncontrolledValue(next);
    }
    onChange?.(next);
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp", "Home", "End"].includes(event.key)) {
      return;
    }
    event.preventDefault();
    if (enabledTabs.length === 0) {
      return;
    }
    const currentIndex = Math.max(
      0,
      enabledTabs.findIndex((tab) => tab.value === selectedTab?.value),
    );
    const nextIndex =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? enabledTabs.length - 1
          : event.key === "ArrowRight" || event.key === "ArrowDown"
            ? (currentIndex + 1) % enabledTabs.length
            : (currentIndex - 1 + enabledTabs.length) % enabledTabs.length;
    const next = enabledTabs[nextIndex];
    if (next) {
      select(next.value);
      document.getElementById(`${baseId}-tab-${next.value}`)?.focus();
    }
  }

  return (
    <div data-terp="tabs" style={rootStyle}>
      <div role="tablist" aria-label={label === undefined ? undefined : resolve(label)} style={tabListStyle} onKeyDown={onKeyDown}>
        {tabs.map((tab) => {
          const selected = tab.value === selectedTab?.value;
          return (
            <button
              key={tab.value}
              id={`${baseId}-tab-${tab.value}`}
              type="button"
              role="tab"
              data-terp="tab"
              aria-selected={selected}
              aria-controls={`${baseId}-panel-${tab.value}`}
              tabIndex={selected ? 0 : -1}
              disabled={tab.disabled}
              onClick={() => select(tab.value)}
              style={tabStyle(selected)}
            >
              {resolve(tab.label)}
            </button>
          );
        })}
      </div>
      {selectedTab && (
        <div
          id={`${baseId}-panel-${selectedTab.value}`}
          role="tabpanel"
          aria-labelledby={`${baseId}-tab-${selectedTab.value}`}
          style={panelStyle}
        >
          {selectedTab.content}
        </div>
      )}
    </div>
  );
}
