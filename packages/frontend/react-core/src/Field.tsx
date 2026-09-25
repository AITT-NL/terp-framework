import { cloneElement, isValidElement, useId } from "react";
import type { HTMLAttributes, ReactNode } from "react";

import type { SpaceToken } from "./layout";
import { injectTerpStyles } from "./styles";
import { mergeDescribedBy, useControlMessages } from "./ui/controlMessages";
import { useUiText } from "./uiText";
import type { UiText } from "./uiText";

injectTerpStyles();

export interface FieldProps {
  /** The field label (also the control's accessible name — the control is wrapped in the `<label>`). */
  label: UiText;
  /** The control: an `<Input>`, `<Select>`, or `<Textarea>`. */
  children: ReactNode;
  /** A field-level error (e.g. mapped from a 422), shown under the control. */
  error?: string | null;
  /** Optional helper text under the control. */
  hint?: UiText;
}

/**
 * A labelled form field: wraps a control in a `<label>` (so the label is its accessible name with no
 * id wiring) and renders an optional hint + a field-level error. Compose it with the token-styled
 * `Input` / `Select` / `Textarea` primitives to build a multi-field form — the centralized, accessible
 * way every module authors inputs.
 *
 * The label needs no wiring because the control sits inside it, but the hint and the error do: text
 * beside a control is invisible to a screen reader unless something points at it. So the field
 * gives each one an id and hands the control an `aria-describedby` — and, when there is an error, an
 * `aria-invalid` that also opts the control into the sheet's invalid border. A control that already
 * declares either keeps its own value; the field adds to `aria-describedby` rather than replacing
 * it. `Input`, `Select`, `Textarea` and `Combobox` all spread their props onto the DOM element, so
 * the attributes land where assistive tech reads them.
 *
 * The error also carries `role="alert"`, and `aria-describedby` is why it has to. A description is
 * read when focus reaches the control, which covers an error that was already there and covers
 * nothing about one that appears on submit — by then focus has left the field, or the button, and
 * the only thing that changed is a span nobody is pointed at. The two are not redundant: they
 * announce at different moments, and a submit-time rejection only has the second one. Because the
 * span is conditional, it enters the accessibility tree exactly when the error appears, which is
 * the event `alert` exists to report.
 */
export function Field({ label, children, error, hint }: FieldProps) {
  const resolve = useUiText();
  const labelId = `${useId()}-label`;
  // Shared with Switch / Checkbox / RadioGroup, which cannot nest inside this component and
  // so carry the same hint/error envelope themselves: one implementation of the ids, the
  // description wiring and the alert, rather than four that drift apart.
  const { hasError, describedBy, messages } = useControlMessages(hint, error);

  // Only a single element child can be named and described — which is the documented contract
  // ("the control"). Anything else is passed through untouched rather than guessed at.
  const control = isValidElement<{
    "aria-describedby"?: string;
    "aria-invalid"?: boolean | "true" | "false";
    "aria-label"?: string;
    "aria-labelledby"?: string;
  }>(children)
    ? cloneElement(children, {
        // The control is named by the label TEXT, not by the label element's subtree, and that
        // distinction is the whole reason this exists. A wrapping label takes its name from
        // everything inside it, so a control that renders an adornment of its own — the password
        // reveal is the first — hands its own button's name to the field: Chromium computes
        // "Password Show password" for that input, which is a WCAG 2.5.3 failure and a sentence
        // no voice-control user can see to say. Pointing at the span makes the name exact.
        //
        // A caller that named the control itself keeps their name; this never overrides one.
        "aria-labelledby":
          children.props["aria-label"] === undefined
            ? (children.props["aria-labelledby"] ?? labelId)
            : undefined,
        "aria-describedby": mergeDescribedBy(
          children.props["aria-describedby"],
          describedBy,
        ),
        "aria-invalid": children.props["aria-invalid"] ?? (hasError ? true : undefined),
      })
    : children;

  return (
    <div data-terp="field">
      <label data-terp="field-label">
        <span id={labelId} data-terp="field-label-text">
          {resolve(label)}
        </span>
        {control}
      </label>
      {messages}
    </div>
  );
}

export interface FieldRowProps extends Omit<HTMLAttributes<HTMLDivElement>, "style"> {
  /**
   * Distance between the columns, as a step on the token spacing scale (default `2`).
   *
   * The COLUMN gap only. The row gap is the field's own label-to-control distance and is
   * not a caller's to move: it is shared by every field in the row, so changing it from
   * the outside would be changing the internal measure of each one.
   */
  gap?: SpaceToken;
  /** The fields, and the actions that belong beside them. */
  children: ReactNode;
}

/**
 * Several {@link Field}s side by side, with their labels, their controls and their
 * messages each on a shared line.
 *
 * It exists because a row of fields had no correct alignment, and both wrong ones were
 * reachable by an ordinary `Stack`. A field is as tall as its label, its control AND
 * whatever it has to say, so in a flex row:
 *
 * - `align="end"` lines up the BOTTOMS, which is the messages. A field that grows a hint
 *   lifts its own control above its neighbours', and a bare action button beside it sinks
 *   to the depth of the longest error on the row. Measured at 44px on a three-field row
 *   the moment one hint appeared.
 * - `align="start"` lines up the TOPS, which fixes the fields and breaks the button: with
 *   no label of its own it rides up level with the labels instead of the controls.
 *
 * Neither is a bug in `Stack`. A flex row can align one edge of a box, and the thing that
 * has to line up here is a band in the MIDDLE of it, which needs the boxes to share tracks
 * rather than edges. So the row owns three rows and each field becomes a subgrid of them --
 * the same instrument {@link DetailListGroup} uses to share one label column across several
 * lists, for the same reason: the alternative is each box measuring itself.
 *
 * Anything that is not a field lands on the control line. That covers the case the row was
 * written for -- a remove button, an add button, a unit select beside an amount -- and it
 * is a placement rather than a wrapper, so the child stays whatever it was.
 *
 * ```tsx
 * <FieldRow>
 *   <Field label={field}><Combobox … /></Field>
 *   <Field label={handling}><Select … /></Field>
 *   <Field label={reason} hint={whyItIsRequired}><Select … /></Field>
 *   <Button variant="ghost" icon={<Icon name="trash" />} aria-label={remove} />
 * </FieldRow>
 * ```
 *
 * **Below the framework's viewport cutover it becomes one column**, each field full width.
 * Three controls and an action do not fit a phone at any gap, and a row that kept its
 * tracks there would either scroll sideways or squeeze every control to unusable. One
 * column is also where the alignment problem stops existing, so nothing is lost by
 * dropping the subgrid with it.
 */
export function FieldRow({ gap, children, ...rest }: FieldRowProps) {
  return (
    <div
      {...rest}
      data-terp="field-row"
      // The gap roll-call's idiom: an unset gap stamps nothing and leaves the base rule
      // standing, rather than restating the default in the DOM.
      data-gap={gap === undefined ? undefined : String(gap)}
    >
      {children}
    </div>
  );
}

