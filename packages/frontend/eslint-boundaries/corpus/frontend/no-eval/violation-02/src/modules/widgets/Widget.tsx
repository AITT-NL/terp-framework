export function run(code: string) {
  return globalThis.eval(code);
}

export function runQualified(code: string) {
  return window.eval(code);
}
