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

interface ComboboxCommonProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "defaultValue" | "onChange" | "children" | "role"> {
  options: readonly ComboboxOption[];
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

/** One selection, or none. */
export interface ComboboxSingleProps extends ComboboxCommonProps {
  multiple?: false;
  value?: string | null;
  defaultValue?: string | null;
  onChange?: (value: string | null, option: ComboboxOption | null) => void;
}

/** A SET of selections, rendered as removable tokens. */
export interface ComboboxMultipleProps extends ComboboxCommonProps {
  multiple: true;
  value?: readonly string[];
  defaultValue?: readonly string[];
  onChange?: (values: readonly string[], options: readonly ComboboxOption[]) => void;
  /** Accessible name for a token's remove control; the option's label is appended. */
  removeLabel?: UiText;
}

/**
 * A mode rather than a second component, and the union is the point: `multiple` decides the
 * shape of `value`, `defaultValue` and `onChange` together, so handing a plain string to a
 * multiple combobox — or an array to a single one — is a typecheck error rather than a
 * runtime surprise. Same reasoning as `ICON_NAMES`: a mistake that the compiler can hold is
 * not worth discovering in a browser.
 */
export type ComboboxProps = ComboboxSingleProps | ComboboxMultipleProps;

function isMultiple(props: ComboboxProps): props is ComboboxMultipleProps {
  return props.multiple === true;
}

/**
 * Filterable ARIA combobox/typeahead, single or multiple.
 *
 * **Why `multiple` is here rather than in a component of its own.** A set-valued field had no
 * sanctioned control at all, and the absence did not stop anyone: it produced comma-separated
 * text boxes with the legal values listed in a grey hint beside them — a closed enum typed as
 * free text, so the validation the value set could have enforced was simply lost. That is
 * ADR 0096's principle rather than a preference: a seam that does not cover the common case is
 * a hole, because the compliant path is unavailable and code goes around it.
 *
 * It is a mode because the hard parts already exist here. The listbox, the filtering, the
 * active-option model, the outside-click close and the whole `aria-activedescendant` wiring
 * are the same; what differs is that a selection is a set, that choosing one keeps the list
 * open, and that the selections need somewhere to live. A second component would have had to
 * re-derive all of the first list and would drift from it.
 */
export function Combobox(props: ComboboxProps) {
  return isMultiple(props) ? <MultiCombobox {...props} /> : <SingleCombobox {...props} />;
}

function MultiCombobox(props: ComboboxMultipleProps) {
  const { value, defaultValue, onChange, removeLabel = "Remove", ...rest } = props;
  const resolve = useUiText();
  const [uncontrolled, setUncontrolled] = useState<readonly string[]>(defaultValue ?? []);
  const selected = value ?? uncontrolled;
  const byValue = useMemo(
    () => new Map(props.options.map((option) => [option.value, option])),
    [props.options],
  );
  // Order follows the SELECTION, not the option list: a token row that reorders itself when a
  // later option is picked moves the target a user was about to click.
  const selectedOptions = selected.flatMap((v) => {
    const option = byValue.get(v);
    return option === undefined ? [] : [option];
  });

  function commitValues(next: readonly string[]) {
    if (value === undefined) {
      setUncontrolled(next);
    }
    onChange?.(
      next,
      next.flatMap((v) => {
        const option = byValue.get(v);
        return option === undefined ? [] : [option];
      }),
    );
  }

  function toggle(option: ComboboxOption) {
    commitValues(
      selected.includes(option.value)
        ? selected.filter((v) => v !== option.value)
        : [...selected, option.value],
    );
  }

  return (
    <ComboboxShell
      {...rest}
      multiple
      selectedValues={selected}
      onSelectOption={toggle}
      onClearSelection={() => commitValues([])}
      tokens={selectedOptions.map((option) => (
        <span key={option.value} data-terp="combobox-token">
          {resolve(option.label)}
          <button
            type="button"
            data-terp="combobox-token-remove"
            // The label carries the option, so a screen reader hears which token this
            // removes rather than one of N identical "Remove" buttons.
            aria-label={`${resolve(removeLabel)} ${resolve(option.label)}`}
            disabled={rest.disabled}
            onClick={() => commitValues(selected.filter((v) => v !== option.value))}
          >
            ×
          </button>
        </span>
      ))}
      onRemoveLast={() => {
        const last = selected.at(-1);
        if (last !== undefined) {
          commitValues(selected.slice(0, -1));
        }
      }}
    />
  );
}

function SingleCombobox({ multiple: _multiple, ...props }: ComboboxSingleProps) {
  const { value, defaultValue = null, onChange, ...rest } = props;
  const resolve = useUiText();
  const [uncontrolled, setUncontrolled] = useState<string | null>(defaultValue);
  const selectedValue = value ?? uncontrolled;
  const selectedOption = props.options.find((option) => option.value === selectedValue) ?? null;

  return (
    <ComboboxShell
      {...rest}
      multiple={false}
      selectedValues={selectedValue === null ? [] : [selectedValue]}
      // The input mirrors the selection's label in single mode, which is the whole
      // difference in how the text box behaves between the two.
      mirroredLabel={selectedOption === null ? "" : resolve(selectedOption.label)}
      onSelectOption={(option) => {
        if (value === undefined) {
          setUncontrolled(option.value);
        }
        onChange?.(option.value, option);
      }}
      onClearSelection={() => {
        if (value === undefined) {
          setUncontrolled(null);
        }
        onChange?.(null, null);
      }}
    />
  );
}

interface ShellProps extends ComboboxCommonProps {
  multiple: boolean;
  selectedValues: readonly string[];
  onSelectOption: (option: ComboboxOption) => void;
  onClearSelection: () => void;
  mirroredLabel?: string;
  tokens?: readonly React.ReactNode[];
  onRemoveLast?: () => void;
}

function ComboboxShell({
  options,
  multiple,
  selectedValues,
  onSelectOption,
  onClearSelection,
  mirroredLabel = "",
  tokens,
  onRemoveLast,
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
}: ShellProps) {
  const resolve = useUiText();
  const baseId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const chosen = useMemo(() => new Set(selectedValues), [selectedValues]);
  const [query, setQuery] = useState(mirroredLabel);
  const [open, setOpen] = useState(defaultOpen);
  const [activeValue, setActiveValue] = useState<string | null>(
    defaultOpen ? selectedValues[0] ?? null : null,
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
    // The second clause is single-mode only: there the box MIRRORS the chosen label, so the
    // text equalling that label means "nothing typed yet" rather than a filter. In multiple
    // mode the box is only ever a filter — there is no one label to mirror — so a query that
    // happens to equal an option's label must still filter to it.
    if (normalized.length === 0 || (!multiple && mirroredLabel !== "" && query === mirroredLabel)) {
      return options;
    }
    return options.filter((option) => resolve(option.label).toLowerCase().includes(normalized));
  }, [multiple, mirroredLabel, options, query, resolve]);
  const enabledOptions = renderedOptions.filter((option) => !option.disabled);
  const activeOption = renderedOptions.find((option) => option.value === activeValue) ?? enabledOptions[0] ?? null;

  useEffect(() => {
    // Only single mode mirrors: in multiple mode this would erase what the user is typing
    // every time a token changes, which is exactly when they are mid-search for the next one.
    if (!multiple) {
      setQuery(mirroredLabel);
    }
  }, [multiple, mirroredLabel]);

  useEffect(() => {
    if (!open) {
      return;
    }
    function onPointerDown(event: PointerEvent | MouseEvent) {
      if (rootRef.current !== null && event.target instanceof Node && !rootRef.current.contains(event.target)) {
        setOpen(false);
        setQuery(multiple ? "" : mirroredLabel);
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("mousedown", onPointerDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("mousedown", onPointerDown);
    };
  }, [multiple, mirroredLabel, open]);

  function commit(option: ComboboxOption | null) {
    if (option?.disabled) {
      return;
    }
    if (option === null) {
      onClearSelection();
      setQuery("");
      setOpen(false);
      setActiveValue(null);
      return;
    }
    onSelectOption(option);
    if (multiple) {
      // The list STAYS OPEN and the filter is cleared: picking one member of a set is
      // almost never the last thing the user wants, and closing after each pick makes
      // choosing three options three round trips through the control.
      setQuery("");
      setActiveValue(option.value);
      return;
    }
    // `mirroredLabel`, never the clicked option's label. In a CONTROLLED combobox the
    // parent may decline the change — `value` stays what it was — and the box has to keep
    // showing what the prop says rather than what was clicked. Uncontrolled reaches the
    // same place one render later: the selection changes, `mirroredLabel` changes with it,
    // and the mirror effect above sets the box. So this line is correct in both modes for
    // the same reason, which the previous three-way conditional was doing by hand.
    setQuery(mirroredLabel);
    setOpen(false);
    setActiveValue(option.value);
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
          setQuery(multiple ? "" : mirroredLabel);
        }
        break;
      case "Backspace":
        // Only with an empty box, so this never eats a character. It is the shortcut every
        // token field has, and it is an ADDITION to the per-token remove buttons rather than
        // a replacement: a keyboard user who does not know the shortcut can still tab to a
        // token and press it.
        if (multiple && query.length === 0) {
          onRemoveLast?.();
        }
        break;
      default:
        break;
    }
  }

  return (
    <div ref={rootRef} data-terp="combobox">
      <div data-terp="combobox-field" data-multiple={multiple ? "true" : undefined}>
        {tokens}
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
              setActiveValue(
                (multiple ? null : selectedValues[0] ?? null) ?? enabledOptions[0]?.value ?? null,
              );
            }
          }}
          onBlur={onBlur}
          onChange={(event) => {
            setQuery(event.currentTarget.value);
            setOpen(true);
            setActiveValue(null);
          }}
          onKeyDown={handleKeyDown}
          style={style}
        />
        {clearable && !disabled && (query.length > 0 || (multiple && chosen.size > 0)) && (
          <button
            type="button"
            data-terp="iconbutton"
            aria-label={multiple ? "Clear all selections" : "Clear selection"}
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
        <div
          id={`${baseId}-listbox`}
          role="listbox"
          aria-multiselectable={multiple ? true : undefined}
          data-terp="combobox-list"
        >
          {loading ? (
            <div role="status" data-terp="combobox-empty">{resolve(loadingText)}</div>
          ) : renderedOptions.length === 0 ? (
            <div data-terp="combobox-empty">{resolve(noOptionsText)}</div>
          ) : (
            renderedOptions.map((option) => {
              const label = resolve(option.label);
              const active = option.value === activeOption?.value;
              const selected = chosen.has(option.value);
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
