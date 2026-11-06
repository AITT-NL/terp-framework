# `frontend/no-framework-markers`

**App-authored source never writes the stack's component markers**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/frontend/eslint-boundaries/catalog/frontend/no-framework-markers.json`.

## Why this rule exists

A conformant stack's components mark the element each of them renders with an identity attribute, and two of the stack's own controls trust that marker: its stylesheet selects on it, and the runtime half of layout-contract identifies a slot's children by it. Anywhere in app-authored frontend source, those markers are never written: not as an attribute in markup, not as the key of a properties object spread onto an element, and not by setting the attribute on an element through the DOM. A hand-written marker borrows a component's styling without composing the component, which gets around no-inline-styling by another door, and it passes the runtime slot check as the component it names while being something else. The markers are the stack's inventory, and only the stack writes them. An app that replaces one of the stack's own screens owns that screen: it composes the stack's components where it wants their look, and its tests locate the screen by the roles and accessible names it renders, never by forging the markers the stack's own screen carries. Any other data attribute an app writes for itself, such as a test identifier, is out of scope.

## How Terp realises this

The reference stack's markers are `data-terp` and every `data-terp-*` attribute, which the components of @terpjs/react-core stamp on the elements they render; its stylesheet is keyed on them (`[data-terp="card"]`) and verifySlotChildren reads them. The check refuses the name as a JSX attribute on any element or component, as the key of an object literal (an inline spread, a hoisted props object, a createElement props bag), and as a literal name passed to `setAttribute`, `setAttributeNS` or `toggleAttribute`, matching it case-insensitively because the DOM lowercases an attribute name written on an HTML element; it also refuses an assignment to a `dataset` key in the same namespace (`dataset.terp`, `dataset.terpPreviewPick`). Reading a marker is not reported. The compliant shape is the component itself (`Card`, `Stack`, ...); an app that passes its own screen to `renderTerpApp({ login })` writes its sign-in steps against that screen's roles and accessible names.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
// terp-allow-no-framework-markers: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## What the check is not required to catch

A check precise enough to have no false positives has limits. This
rule's limits are recorded as data (its corpus's `RESIDUALS.json`), so
where detection ends is a statement rather than a guess:

- an attribute name that is not a literal (`element.setAttribute(name, value)`, a computed key `{ [name]: value }`) is not required to be resolved to a marker
- a marker written by a route other than an attribute in markup, a properties-object key, an attribute-setting call or a data-attribute-map assignment (`Object.assign(element.dataset, { terp: "card" })`, an attribute node built with `document.createAttribute`) is not required to be recognised

**These are not exemptions.** The rule governs those forms exactly as it
governs any other — a checker is simply not required to find them, so
review is the control there. The list only shrinks: closing one means
adding the corpus case that contracts it.

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `@terpjs/eslint-boundaries` — `terp/no-framework-markers`
