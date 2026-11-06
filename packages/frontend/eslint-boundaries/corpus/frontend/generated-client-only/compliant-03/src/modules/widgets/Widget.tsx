export function Widget() {
  // One catalog rule, one marker: it covers every detection path of the egress
  // family (bare and window-qualified alike).
  // terp-allow-generated-client-only: sanctioned probe for a health widget
  void window.fetch("/healthz");
  return null;
}
