import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { InputHTMLAttributes, KeyboardEvent } from "react";

import { injectTerpStyles } from "../styles";
import { useUiText } from "../uiText";
import type { UiText } from "../uiText";

injectTerpStyles();

export interface ComboboxOption {
  value: string;
  label: UiText;
  disabled?: boolean;
}

export interface ComboboxProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "defaultValue" | "onChange" | "children" | "role"> {
  options: readonly ComboboxOption[];
  value?: string | null;
  defaultValue?: string | null;
  onChange?: (value: string | null, option: ComboboxOption | null) => void;
  loading?: boolean;
  loadingText?: UiText;
  noOptionsText?: UiText;
  clearable?: boolean;
  /**
   * Open the listbox on mount (uncontrolled), the same shape `Popover` and `Menu` take.
   *
   * The cursor starts on the selection rather than nowhere, which is what focusing the box
   * does — an already-open list with no active option would be a state the component cannot
   * otherwise reach.
   */
  defaultOpen?: boolean;
}

/** Filterable ARIA combobox/typeahead with controlled or uncontrolled single selection. */
export function Combobox({
  options,
  value,
  defaultValue = null,
  onChange,
  loading = false,
  loadingText = "Loading…",
  noOptionsText = "No options",
  clearable = false,
  defaultOpen = false,
  disabled,
  onBlur,
  onFocus,
  onKeyDown,
  placeholder,
  style,
  ...rest
}: ComboboxProps) {
  const resolve = useUiText();
  const baseId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [uncontrolledValue, setUncontrolledValue] = useState<string | null>(defaultValue);
  const selectedValue = value ?? uncontrolledValue;
  const selectedOption = options.find((option) => option.value === selectedValue) ?? null;
  const [query, setQuery] = useState(() => (selectedOption ? resolve(selectedOption.label) : ""));
  const [open, setOpen] = useState(defaultOpen);
  const [activeValue, setActiveValue] = useState<string | null>(
    defaultOpen ? selectedOption?.value ?? null : null,
  );

  // What the DOM should say, as opposed to what the state happens to hold. The listbox render
  // was already guarded on `disabled` while aria-expanded was not, so a disabled combobox seeded
  // open advertised role="combobox" aria-expanded="true" with aria-controls pointing at an id
  // that is not in the document. Derived once, so the three cannot drift apart again.
  const isOpen = open && disabled !== true;

  const renderedOptions = useMemo(() => {
    // `toLowerCase`, not the locale-aware fold: this decides whether a substring MATCHES, and a
    // match is not a presentation question for the host to answer. Folded against a Turkish host,
    // `Item` becomes `ıtem` — dotless — which does not contain the `i` the user typed, so every
    // option with a capital I disappears for a Turkish visitor and for nobody else.
    // Folding both sides with the same host locale does not rescue it: the needle comes from a
    // keyboard and the haystack from a server, and the two agree only when the fold is invariant.
    const normalized = query.trim().toLowerCase();
    if (normalized.length === 0 || selectedOption !== null && query === resolve(selectedOption.label)) {
      return options;
    }
    return options.filter((option) => resolve(option.label).toLowerCase().includes(normalized));
  }, [options, query, resolve, selectedOption]);
  const enabledOptions = renderedOptions.filter((option) => !option.disabled);
  const activeOption = renderedOptions.find((option) => option.value === activeValue) ?? enabledOptions[0] ?? null;

  useEffect(() => {
    setQuery(selectedOption ? resolve(selectedOption.label) : "");
  }, [resolve, selectedOption]);

  useEffect(() => {
    if (!open) {
      return;
    }
    function onPointerDown(event: PointerEvent | MouseEvent) {
      if (rootRef.current !== null && event.target instanceof Node && !rootRef.current.contains(event.target)) {
        setOpen(false);
        setQuery(selectedOption ? resolve(selectedOption.label) : "");
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("mousedown", onPointerDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("mousedown", onPointerDown);
    };
  }, [open, resolve, selectedOption]);

  function commit(option: ComboboxOption | null) {
    if (option?.disabled) {
      return;
    }
    if (value === undefined) {
      setUncontrolledValue(option?.value ?? null);
    }
    setQuery(option ? (value === undefined ? resolve(option.label) : selectedOption ? resolve(selectedOption.label) : "") : "");
    setOpen(false);
    setActiveValue(option?.value ?? null);
    onChange?.(option?.value ?? null, option);
  }

  function moveActive(direction: 1 | -1 | "first" | "last") {
    if (enabledOptions.length === 0) {
      return;
    }
    const current = enabledOptions.findIndex((option) => option.value === activeOption?.value);
    const nextIndex = direction === "first"
      ? 0
      : direction === "last"
        ? enabledOptions.length - 1
        : current < 0
          ? 0
          : (current + direction + enabledOptions.length) % enabledOptions.length;
    setActiveValue(enabledOptions[nextIndex]?.value ?? null);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    onKeyDown?.(event);
    if (event.defaultPrevented) {
      return;
    }
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        setOpen(true);
        moveActive(1);
        break;
      case "ArrowUp":
        event.preventDefault();
        setOpen(true);
        moveActive(-1);
        break;
      case "Home":
        if (open) {
          event.preventDefault();
          moveActive("first");
        }
        break;
      case "End":
        if (open) {
          event.preventDefault();
          moveActive("last");
        }
        break;
      case "Enter":
        if (open && activeOption !== null) {
          event.preventDefault();
          commit(activeOption);
        }
        break;
      case "Escape":
        if (open) {
          event.preventDefault();
          setOpen(false);
          setQuery(selectedOption ? resolve(selectedOption.label) : "");
        }
        break;
      default:
        break;
    }
  }

  return (
    <div ref={rootRef} data-terp="combobox">
      <div data-terp="combobox-field">
        <input
          {...rest}
          ref={inputRef}
          data-terp="input"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={isOpen}
          aria-controls={`${baseId}-listbox`}
          aria-activedescendant={isOpen && activeOption !== null ? `${baseId}-option-${activeOption.value}` : undefined}
          aria-invalid={rest["aria-invalid"]}
          disabled={disabled}
          placeholder={placeholder}
          value={query}
          onFocus={(event) => {
            onFocus?.(event);
            if (!disabled) {
              setOpen(true);
              setActiveValue(selectedOption?.value ?? enabledOptions[0]?.value ?? null);
            }
          }}
          onBlur={onBlur}
          onChange={(event) => {
            setQuery(event.currentTarget.value);
            setOpen(true);
            setActiveValue(null);
            if (selectedValue !== null && value === undefined) {
              setUncontrolledValue(null);
            }
          }}
          onKeyDown={handleKeyDown}
          style={style}
        />
        {clearable && !disabled && query.length > 0 && (
          <button
            type="button"
            data-terp="iconbutton"
            aria-label="Clear selection"
            onClick={() => {
              commit(null);
              inputRef.current?.focus();
            }}
          >
            ×
          </button>
        )}
      </div>
      {isOpen && (
        <div id={`${baseId}-listbox`} role="listbox" data-terp="combobox-list">
          {loading ? (
            <div role="status" data-terp="combobox-empty">{resolve(loadingText)}</div>
          ) : renderedOptions.length === 0 ? (
            <div data-terp="combobox-empty">{resolve(noOptionsText)}</div>
          ) : (
            renderedOptions.map((option) => {
              const label = resolve(option.label);
              const active = option.value === activeOption?.value;
              const selected = option.value === selectedValue;
              return (
                <button
                  key={option.value}
                  id={`${baseId}-option-${option.value}`}
                  type="button"
                  role="option"
                  aria-selected={selected}
                  disabled={option.disabled}
                  tabIndex={-1}
                  onMouseDown={(event) => event.preventDefault()}
                  onMouseEnter={() => setActiveValue(option.value)}
                  onClick={() => commit(option)}
                  data-terp="combobox-option"
                  data-active={active ? "true" : undefined}
                >
                  {label}
                </button>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
