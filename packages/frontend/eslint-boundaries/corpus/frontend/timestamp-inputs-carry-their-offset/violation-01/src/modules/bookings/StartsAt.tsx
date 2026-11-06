import { Input } from "@terpjs/react-core";

export function StartsAt() {
  // The control's own value is a wall time with no UTC offset, which names no instant.
  return <Input type="datetime-local" />;
}
