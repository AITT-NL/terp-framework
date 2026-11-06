export function newKey() {
  return globalThis.crypto.randomUUID();
}
