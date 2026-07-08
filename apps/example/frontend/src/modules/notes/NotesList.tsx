import { OverviewPage, ResourceList } from "@terp/react-core";

import { useNotes } from "./useNotes";

/** The notes overview page — the shared ResourceList composed with the notes data hook. */
export function NotesList() {
  const notes = useNotes();
  return (
    <OverviewPage title="Notes">
      <ResourceList
        resource={notes}
        createPlaceholder="New note title"
        renderItem={(note) => <strong>{note.title}</strong>}
      />
    </OverviewPage>
  );
}
