export function Widget() {
  // A marker that names no rule with a governed opt-out (a typo, a stale name,
  // or the governance rule's own name) is itself a violation - it can never be
  // budgeted into legitimacy.
  // terp-allow-made-up-rule: stale name
  return null;
}
