export function Widget() {
  // Markers live in real comments only: marker-shaped text inside a string
  // neither suppresses the next line nor its own line.
  const doc = "// terp-allow-no-eval: not a comment";
  return eval(doc);
}
