export async function copyReference(value: string) {
  await navigator.clipboard.writeText(value);
}
