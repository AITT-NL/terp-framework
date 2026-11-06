export function nonce() {
  return crypto.getRandomValues(new Uint8Array(16));
}
