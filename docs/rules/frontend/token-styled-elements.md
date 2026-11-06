# `frontend/token-styled-elements`

**Raw interactive/structural HTML elements are refused in app modules**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/frontend/eslint-boundaries/catalog/frontend/token-styled-elements.json`.

## Why this rule exists

A raw <button>/<input>/<select>/<textarea>/<table>/<dialog>/<form>/<meter> bypasses the app's sanctioned, token-styled primitive surface (accessible and theme-consistent by construction). The refused elements are declared in restricted-surface.json (restrictedElements); each has a sanctioned replacement in the stack's component surface, and the violation message names it.

## How Terp realises this

Button, Input, Select, Textarea, DataView, ConfirmDialog, Stack as="form" and Meter from @terpjs/react-core (BOUNDARY_SPEC.restrictedElements maps each element to its replacement).

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
// terp-allow-token-styled-elements: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `@terpjs/eslint-boundaries` — `BOUNDARY_SPEC.restrictedElements`
