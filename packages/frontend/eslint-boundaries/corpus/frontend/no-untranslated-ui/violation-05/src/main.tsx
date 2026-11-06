import { useToast } from "@terpjs/react-core";

export function SaveAction() {
  const toast = useToast();
  toast.success("Changes saved");
  return null;
}
