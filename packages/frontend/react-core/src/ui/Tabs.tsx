import { useId, useMemo, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";

import { injectTerpStyles } from "../styles";
import { useUiText } from "../uiText";
import type { UiText } from "../uiText";

injectTerpStyles();

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
  // Element ids are built from the tab's INDEX, never from its `value`. A value is caller data
  // and an id is an IDREF: a value containing whitespace turns `aria-labelledby` into a list of
  // two tokens, neither of which resolves, and the tabpanel silently loses its accessible name.
  // Nothing reports that — axe sees a well-formed reference to nothing. The same refusal to
  // interpolate caller strings into ids is written out at AppShell's nav-group labels.
  const selectedIndex = tabs.findIndex((tab) => tab.value === selectedTab?.value);

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
      // Looked up by the tab's position in `tabs`, matching the id it was rendered with.
      // `enabledTabs` is a filtered view, so its index is not the rendered one.
      document
        .getElementById(`${baseId}-tab-${tabs.findIndex((tab) => tab.value === next.value)}`)
        ?.focus();
    }
  }

  return (
    <div data-terp="tabs">
      <div role="tablist" data-terp="tab-list" aria-label={label === undefined ? undefined : resolve(label)} onKeyDown={onKeyDown}>
        {tabs.map((tab, index) => {
          const selected = tab.value === selectedTab?.value;
          return (
            <button
              key={tab.value}
              id={`${baseId}-tab-${index}`}
              type="button"
              role="tab"
              data-terp="tab"
              aria-selected={selected}
              aria-controls={`${baseId}-panel-${index}`}
              tabIndex={selected ? 0 : -1}
              disabled={tab.disabled}
              onClick={() => select(tab.value)}
            >
              {resolve(tab.label)}
            </button>
          );
        })}
      </div>
      {selectedTab && (
        <div
          id={`${baseId}-panel-${selectedIndex}`}
          role="tabpanel"
          aria-labelledby={`${baseId}-tab-${selectedIndex}`}
          data-terp="tab-panel"
        >
          {selectedTab.content}
        </div>
      )}
    </div>
  );
}
