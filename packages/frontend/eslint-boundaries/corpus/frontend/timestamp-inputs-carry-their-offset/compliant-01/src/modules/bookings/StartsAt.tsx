import { DateTimeInput } from "@terpjs/react-core";

interface StartsAtProps {
  value: string | null;
  onChange: (value: string | null) => void;
}

export function StartsAt({ value, onChange }: StartsAtProps) {
  // Shown in the zone, and sent as the instant it names, with the zone's offset.
  return <DateTimeInput value={value} onChange={onChange} zone="Europe/Amsterdam" />;
}
