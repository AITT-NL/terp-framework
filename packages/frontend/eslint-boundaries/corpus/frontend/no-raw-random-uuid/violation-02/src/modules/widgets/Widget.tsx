export function newKey() {
  const { randomUUID } = crypto;
  return randomUUID();
}
