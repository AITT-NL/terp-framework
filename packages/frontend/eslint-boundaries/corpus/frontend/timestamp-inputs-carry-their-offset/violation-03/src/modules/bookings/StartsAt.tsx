import { Input } from "@terpjs/react-core";

interface StartsAtProps {
  withTime: boolean;
}

export function StartsAt({ withTime }: StartsAtProps) {
  // The value is followed wherever it is spelled inline: a branch of a conditional can be the
  // local date-and-time control as surely as a string can.
  return <Input type={withTime ? "datetime-local" : "date"} />;
}
