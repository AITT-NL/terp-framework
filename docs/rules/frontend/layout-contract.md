# `frontend/layout-contract`

**An opted-in app's archetype body slots accept only the contract's components**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/frontend/eslint-boundaries/catalog/frontend/layout-contract.json`.

## Why this rule exists

With a checked-in layout declaration, each page archetype's body slot is constrained to the contract's sanctioned components, so screens stay structurally consistent and the failure message tells an agent exactly how to build the screen. Paired with the fail-closed runtime check on the rendered slot. The declaration is the single source for the opt-in, for the palette the app opens on, and for the shell's own shape down to the navigation groups a module's items name by id and the mark the app is recognised by (layout-declaration.schema.json): a build-time checker and the running app read the same document, so neither can enforce a contract the other does not, and a key declared both in the document and in the app's own code is refused rather than resolved by an invisible precedence.

## How Terp realises this

frontend/layout-contract.json, the document layout-declaration.schema.json describes (ADR 0079); the app imports it and the reference stack's bootstrap resolves it, refusing an unknown key, a value outside its enum, and any key declared twice. The per-stack values: contracts are the keys of LAYOUT_CONTRACTS in @terpjs/react-core, and defaultTheme names one of the palettes @terpjs/contract compiles or the reserved system. Neither list is written out here: the contract ids and the palette names both live in @terpjs/react-core's published layout.manifest.json, with the values filled in for the release an app is pinned to, and every copy of them in that stack is gated against it. A fourth copy in this field would be the one nothing checks, and it would sit in the very field this schema points a reader at for the truth. shell.navGroups is groupNav's group table in @terpjs/react-core, whose NavItem.group references it; shell.brand names paths Vite serves from the app's own frontend/public, rendered into AppShell's logo and logoDark slots. verifySlotChildren in @terpjs/react-core is the runtime DOM check.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
// terp-allow-layout-contract: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `@terpjs/eslint-boundaries` — `terp/layout-contract`
- `runtime`: `@terpjs/react-core` — `verifySlotChildren`
