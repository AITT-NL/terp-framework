export function Widget() {
  // A marker spelled with a RETIRED tool-internal rule id (the pre-0.6.0
  // core-id spelling) names no catalog rule, so it waives nothing: the
  // violation underneath still fires and the stale marker is itself reported.
  // terp-allow-no-restricted-syntax: pre-0.6.0 spelling (migrate to the catalog rule name)
  return <button>x</button>;
}
