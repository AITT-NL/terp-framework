export async function copyReference(value: string) {
  const { clipboard } = navigator;
  await clipboard.writeText(value);
}
