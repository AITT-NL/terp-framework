import { copyText } from "@terpjs/react-core";

export async function copyReference(value: string) {
  return copyText(value);
}
