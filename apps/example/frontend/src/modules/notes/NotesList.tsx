import {
  Alert,
  OverviewPage,
  ResourceList,
  Stack,
  useRealtimeChannel,
} from "@terpjs/react-core";

import { useNotes } from "./useNotes";

interface SystemNotice {
  sequence: number;
  text: string;
}

function isSystemNotice(value: unknown): value is SystemNotice {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Record<string, unknown>;
  return typeof item.sequence === "number" && typeof item.text === "string";
}

/** The notes overview page — the shared ResourceList composed with the notes data hook. */
export function NotesList() {
  const notes = useNotes();
  const notices = useRealtimeChannel({
    channel: "system.notices",
    validate: isSystemNotice,
  });
  return (
    <OverviewPage title="Notes">
      <Stack>
        {notices.lastMessage && (
          <Alert title="Live system notice">{notices.lastMessage.text}</Alert>
        )}
        <ResourceList
          resource={notes}
          createPlaceholder="New note title"
          renderItem={(note) => <strong>{note.title}</strong>}
        />
      </Stack>
    </OverviewPage>
  );
}
