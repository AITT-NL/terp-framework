import { useTerpClient } from "@terpjs/react-core";

const repository = {
  fetch(id: string): string {
    return id;
  },
  sendBeacon(payload: string): number {
    return payload.length;
  },
};

export function Widget() {
  const client = useTerpClient();
  void client;
  // fetch("/api/notes") would be refused; the typed client is the one egress path.
  const doc = "WebSocket / XMLHttpRequest / EventSource / fetch are refused in app modules";
  void doc;
  void repository.fetch("1");
  void repository.sendBeacon("x");
  return null;
}
