import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { CSSProperties, InputHTMLAttributes, KeyboardEvent } from "react";

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
}

const wrapperStyle: CSSProperties = { position: "relative", display: "grid" };
const inputWrapStyle: CSSProperties = { position: "relative", display: "grid" };
const inputStyle: CSSProperties = {
  font: "inherit",
  lineHeight: 1.2,
  width: "100%",
  minWidth: 0,
  minHeight: "2.25rem",
  padding: "0 calc(var(--space-3) + 1.5rem) 0 var(--space-3)",
  border: "1px solid var(--color-neutral-300)",
  borderRadius: "var(--radius-md)",
  color: "var(--color-neutral-900)",
  background: "var(--color-neutral-0)",
  boxSizing: "border-box",
};
const clearStyle: CSSProperties = {
  position: "absolute",
  insetInlineEnd: "var(--space-1)",
  insetBlockStart: "50%",
  transform: "translateY(-50%)",
  border: "none",
  background: "transparent",
  color: "var(--color-neutral-500)",
  cursor: "pointer",
  minWidth: "1.75rem",
  minHeight: "1.75rem",
  borderRadius: "var(--radius-sm)",
};
const listStyle: CSSProperties = {
  position: "absolute",
  insetInlineStart: 0,
  insetInlineEnd: 0,
  insetBlockStart: "calc(100% + var(--space-1))",
  zIndex: 50,
  display: "grid",
  gap: "var(--space-1)",
  maxHeight: "16rem",
  overflowY: "auto",
  padding: "var(--space-1)",
  background: "var(--color-neutral-0)",
  border: "1px solid var(--color-neutral-200)",
  borderRadius: "var(--radius-lg)",
  boxShadow: "var(--shadow-lg)",
};
const optionStyle = (active: boolean, selected: boolean, disabled: boolean): CSSProperties => ({
  font: "inherit",
  textAlign: "left",
  padding: "var(--space-2) var(--space-3)",
  border: "none",
  borderRadius: "var(--radius-sm)",
  background: active ? "var(--color-neutral-100)" : "transparent",
  color: disabled
    ? "var(--color-neutral-400)"
    : selected
      ? "var(--color-brand-primary)"
      : "var(--color-neutral-900)",
  cursor: disabled ? "not-allowed" : "pointer",
  fontWeight: selected ? "var(--font-weight-semibold)" as never : "var(--font-weight-regular)" as never,
});
const emptyStyle: CSSProperties = {
  padding: "var(--space-2) var(--space-3)",
  color: "var(--color-neutral-500)",
  fontSize: "var(--font-size-sm)",
};

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
  const [open, setOpen] = useState(false);
  const [activeValue, setActiveValue] = useState<string | null>(null);

  const renderedOptions = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    if (normalized.length === 0 || selectedOption !== null && query === resolve(selectedOption.label)) {
      return options;
    }
    return options.filter((option) => resolve(option.label).toLocaleLowerCase().includes(normalized));
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
    <div ref={rootRef} style={wrapperStyle}>
      <div style={inputWrapStyle}>
        <input
          {...rest}
          ref={inputRef}
          data-terp="input"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={open}
          aria-controls={`${baseId}-listbox`}
          aria-activedescendant={open && activeOption !== null ? `${baseId}-option-${activeOption.value}` : undefined}
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
          style={{ ...inputStyle, ...style }}
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
            style={clearStyle}
          >
            ×
          </button>
        )}
      </div>
      {open && !disabled && (
        <div id={`${baseId}-listbox`} role="listbox" style={listStyle}>
          {loading ? (
            <div role="status" style={emptyStyle}>{resolve(loadingText)}</div>
          ) : renderedOptions.length === 0 ? (
            <div style={emptyStyle}>{resolve(noOptionsText)}</div>
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
                  style={optionStyle(active, selected, option.disabled === true)}
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
