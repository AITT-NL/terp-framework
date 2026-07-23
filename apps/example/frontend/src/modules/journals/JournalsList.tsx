import { Button, Field, Input, OverviewPage, ResourceList, Stack, Textarea } from "@terpjs/react-core";
import { useState } from "react";
import type { FormEvent } from "react";

import { useJournals } from "./useJournals";

/** A multi-field create form (title + a multi-line entry), composed from the shared form primitives. */
function NewJournalForm({ onAdd }: { onAdd: (title: string, entry: string) => Promise<void> }) {
  const [title, setTitle] = useState("");
  const [entry, setEntry] = useState("");

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!title.trim()) {
      return;
    }
    try {
      await onAdd(title, entry);
      setTitle("");
      setEntry("");
    } catch {
      // Surfaced via the resource error (rendered by ResourceList); keep the draft to retry.
    }
  }

  return (
    <Stack as="form" onSubmit={onSubmit}>
      <Field label="Title">
        <Input value={title} onChange={(event) => setTitle(event.target.value)} />
      </Field>
      <Field label="Entry">
        <Textarea value={entry} onChange={(event) => setEntry(event.target.value)} rows={3} />
      </Field>
      <Button type="submit">Add</Button>
    </Stack>
  );
}

/** The journals overview page (each entry is owned by its creator on the backend). */
export function JournalsList() {
  const journals = useJournals();
  return (
    <OverviewPage title="Journals">
      <ResourceList
        resource={journals}
        renderCreate={() => <NewJournalForm onAdd={journals.add} />}
        renderItem={(journal) => <strong>{journal.title}</strong>}
      />
    </OverviewPage>
  );
}
