import { useCallback, useEffect, useRef, useState } from "react";

export interface UseViewSearchResult {
  /** The immediate input value (what the user is typing). */
  inputValue: string;
  /** Update the input; the outer `onChange` fires after the debounce window. */
  setInputValue: (value: string) => void;
  /** Clear the input and emit "" immediately (the × button). */
  clear: () => void;
}

/**
 * Controlled search-input state with an optional debounce: the input updates
 * immediately, the outer `onChange` (which typically triggers a repository query)
 * fires only after `debounceMs` of quiet. External changes to `value` (e.g. a
 * "clear filters" reset) sync back into the input.
 */
export function useViewSearch(
  value: string,
  onChange: (value: string) => void,
  debounceMs = 0,
): UseViewSearchResult {
  const [inputValue, setInput] = useState(value);
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  // Track the last value we emitted, so an echo of our own change does not clobber
  // what the user typed since.
  const lastEmittedRef = useRef(value);

  useEffect(() => {
    if (value !== lastEmittedRef.current) {
      // An external reset wins: cancel any pending debounced emit so it cannot
      // resurrect the value the caller just cleared.
      clearTimeout(timerRef.current);
      lastEmittedRef.current = value;
      setInput(value);
    }
  }, [value]);

  useEffect(() => () => clearTimeout(timerRef.current), []);

  const emit = useCallback((next: string) => {
    lastEmittedRef.current = next;
    onChangeRef.current(next);
  }, []);

  const setInputValue = useCallback(
    (next: string) => {
      setInput(next);
      clearTimeout(timerRef.current);
      if (debounceMs <= 0) {
        emit(next);
      } else {
        timerRef.current = setTimeout(() => emit(next), debounceMs);
      }
    },
    [debounceMs, emit],
  );

  const clear = useCallback(() => {
    setInput("");
    clearTimeout(timerRef.current);
    emit("");
  }, [emit]);

  return { inputValue, setInputValue, clear };
}
