// A minimal CSS rule reader for the token-sheet gates.
//
// Not a general parser and not exported from the package (`exports` in package.json
// publishes only the entry, the schema, the OpenAPI document and the sheet itself). It
// exists because two gates read `tokens.css` and a naive "slice to the next `}`" scan is
// wrong in a way that passes: a value containing a brace, or an `@media` wrapper, ends the
// block early and the gate then asserts about a fragment.

/**
 * Every `selector { … }` rule in `css`, flattened.
 *
 * An `@media` (or any other conditional group) contributes its inner rules rather than
 * itself, so a nested `:root` is reachable by selector. A statement at-rule — `@charset`,
 * `@import`, `@layer a, b;` — declares no block and is skipped; without that, its trailing
 * `;` would let the scan run on to the *next* rule's brace and silently merge two rules.
 *
 * @param {string} css
 * @returns {{ selector: string, declarations: Map<string, string> }[]}
 */
export function parseRules(css) {
  const source = stripComments(css);
  const rules = [];
  let index = 0;
  while (index < source.length) {
    const open = source.indexOf("{", index);
    if (open === -1) break;
    // A `;` before the next `{` means the run of text is a statement at-rule, not a
    // selector: consume it and carry on rather than treating the following block as its own.
    const statementEnd = source.indexOf(";", index);
    if (statementEnd !== -1 && statementEnd < open) {
      index = statementEnd + 1;
      continue;
    }
    const selector = source.slice(index, open).trim();
    let depth = 1;
    let cursor = open + 1;
    // Quote-aware: a brace inside a quoted value (a font stack, a `url()`, a `content`
    // string) is data, not structure. Counting it would end the block early and leave every
    // later declaration in the rule unread — silently, because the fragment still parses.
    let quote = "";
    while (cursor < source.length && depth > 0) {
      const character = source[cursor];
      if (quote) {
        if (character === "\\") cursor += 1;
        else if (character === quote) quote = "";
      } else if (character === '"' || character === "'") {
        quote = character;
      } else if (character === "{") depth += 1;
      else if (character === "}") depth -= 1;
      cursor += 1;
    }
    const body = source.slice(open + 1, cursor - 1);
    if (selector.startsWith("@")) {
      rules.push(...parseRules(body));
    } else if (selector) {
      rules.push({ selector, declarations: parseDeclarations(body) });
    }
    index = cursor;
  }
  return rules;
}

/**
 * The `--token: value` custom properties declared directly in a rule body, in source order.
 *
 * @param {string} body
 * @returns {Map<string, string>}
 */
export function parseDeclarations(body) {
  const declarations = new Map();
  for (const match of body.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/g)) {
    declarations.set(match[1], match[2].trim());
  }
  return declarations;
}

/** `css` with `/* … *\/` comments removed. */
export function stripComments(css) {
  return css.replace(/\/\*[\s\S]*?\*\//g, "");
}
