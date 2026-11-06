import { Trans, useRealtimeChannel } from "@terpjs/react-core";

type Notice = { sequence: number; text: string };

function isNotice(value: unknown): value is Notice {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Record<string, unknown>;
  return typeof item.sequence === "number" && typeof item.text === "string";
}

export function Widget() {
  const notices = useRealtimeChannel({
    channel: "system.notices",
    validate: isNotice,
  });
  return (
    <p>
      {notices.lastMessage?.text ?? <Trans id="realtime.waiting" message="Waiting" />}
    </p>
  );
}
