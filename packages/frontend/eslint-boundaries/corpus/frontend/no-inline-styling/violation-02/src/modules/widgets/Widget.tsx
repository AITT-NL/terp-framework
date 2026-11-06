export function Widget() {
  // A justified marker for a SIBLING catalog rule sharing the same core lint id
  // never waives this one: the marker names the catalog rule, not the tool rule.
  // terp-allow-token-styled-elements: wrong rule - must not suppress the style attribute
  return <div style={{ color: "#ff0000" }}>save</div>;
}
