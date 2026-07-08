import { useState } from "react";
import type { CSSProperties, FormEvent, ReactNode } from "react";

import { Authorized } from "./Authorized";
import { useErrorMessage } from "./errorMessages";
import { useStrings, useUiText } from "./uiText";
import type { UiText } from "./uiText";
import { Button } from "./ui/Button";
import { Input } from "./ui/Input";
import type { Resource } from "./useResource";

const rowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: "var(--space-3)",
  padding: "var(--space-3)",
  border: "1px solid var(--color-neutral-200)",
  borderRadius: "var(--radius-md)",
  background: "var(--color-neutral-0)",
};

const mutedStyle: CSSProperties = { color: "var(--color-neutral-600)" };

export interface ResourceListProps<T extends { id: string }> {
  /** Section heading; omit when composed under a `Page` (whose title is the `h1`). */
  title?: UiText;
  /** The module's data hook result (items / loading / error / create — see {@link useResource}). */
  resource: Resource<T, string>;
  /** Render the content of one row. */
  renderItem: (item: T) => ReactNode;
  /** Placeholder for the single-field create input; omit to hide creating. */
  createPlaceholder?: UiText;
  /**
   * A custom (e.g. multi-field) create form, for creates that need more than one field. Supply a
   * component built from `Field` + the input primitives; ResourceList still applies the write-gate
   * around it. Overrides `createPlaceholder`.
   */
  renderCreate?: () => ReactNode;
  /** Optional per-row actions (e.g. a delete button); rendered only for writers. */
  renderActions?: (item: T) => ReactNode;
  /** Message shown when there are no rows (default: the `emptyList` string). */
  emptyMessage?: UiText;
}

/**
 * The standard list screen every CRUD module needs, centralized: a titled section, a write-gated
 * single-field create form, loading / error / empty states, and a token-styled list. A module
 * composes it with its typed data hook and a row renderer, so every module lists and creates the
 * same way — and the {@link Authorized} write-gate (create form + row actions) is applied for you,
 * not re-implemented per module.
 *
 * It is a composable component, not a hidden CRUD DSL: a screen that needs more just renders its own
 * React and ignores this.
 */
export function ResourceList<T extends { id: string }>({
  title,
  resource,
  renderItem,
  createPlaceholder,
  renderCreate,
  renderActions,
  emptyMessage,
}: ResourceListProps<T>) {
  const strings = useStrings();
  const resolve = useUiText();
  const messageForCode = useErrorMessage();
  const [draft, setDraft] = useState("");

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    if (!draft.trim()) {
      return;
    }
    try {
      await resource.create(draft);
      setDraft(""); // clear only on success; a failed create surfaces resource.error and keeps the draft
    } catch {
      // The failure is already surfaced via resource.error (rendered below); keep the draft to retry.
    }
  }

  return (
    <section
      data-terp="resource-list"
      style={{ display: "grid", gap: "var(--space-4)", maxWidth: "40rem" }}
    >
      {title !== undefined && <h1>{resolve(title)}</h1>}
      {renderCreate !== undefined ? (
        <Authorized action="write">{renderCreate()}</Authorized>
      ) : createPlaceholder !== undefined ? (
        <Authorized action="write">
          <form onSubmit={onCreate} style={{ display: "flex", gap: "var(--space-2)" }}>
            <Input
              placeholder={resolve(createPlaceholder ?? "")}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              style={{ flex: 1 }}
            />
            <Button type="submit">{strings.add}</Button>
          </form>
        </Authorized>
      ) : null}
      {resource.error !== null && (
        <p role="alert" style={{ color: "var(--color-status-danger)" }}>
          {messageForCode(resource.cause) ?? resource.error}
        </p>
      )}
      {resource.items.length === 0 ? (
        <p style={mutedStyle}>{resource.loading ? strings.loading : resolve(emptyMessage ?? strings.emptyList)}</p>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: "var(--space-2)" }}>
          {resource.items.map((item) => (
            <li key={item.id} style={rowStyle}>
              <div>{renderItem(item)}</div>
              {renderActions && <Authorized action="write">{renderActions(item)}</Authorized>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
