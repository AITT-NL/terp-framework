import { Input } from "@terpjs/react-core";

export function StartsAt() {
  // The browser reads the type in any letter case, so the rule does too, in an expression or a
  // plain template as much as in a string.
  return (
    <>
      <Input type={"DATETIME-LOCAL"} />
      <Input type={`datetime-local`} />
    </>
  );
}
