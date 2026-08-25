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

  // One usable tab is not a choice, so it gets no chrome. A tablist over a single tab costs
  // a row of the screen to offer nothing, and it is worse than decorative to a screen
  // reader: the set announces "tab 1 of 1" and the only affordance is already selected.
  // Rendering the content bare also drops the tabpanel, which is correct rather than
  // convenient — a panel exists to be labelled by the tab that reveals it, and there is
  // no revealing left to do.
  //
  // A single DISABLED tab keeps the chrome, deliberately: there the tab set is carrying
  // real information (this section exists and is unavailable), and silently rendering its
  // content would show what the caller marked unreachable.
  if (tabs.length === 1 && !tabs[0]?.disabled) {
    return <>{tabs[0]?.content}</>;
  }

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
