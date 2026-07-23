import { Button, Field, Input, OverviewPage, ResourceList, Select, Stack } from "@terpjs/react-core";
import { useState } from "react";
import type { FormEvent } from "react";

import { useTasks } from "./useTasks";

/** A multi-field create form (title + status), composed from the shared form primitives. */
function NewTaskForm({ onAdd }: { onAdd: (title: string, status: string) => Promise<void> }) {
  const [title, setTitle] = useState("");
  const [status, setStatus] = useState("open");

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!title.trim()) {
      return;
    }
    try {
      await onAdd(title, status);
      setTitle("");
      setStatus("open");
    } catch {
      // Surfaced via the resource error (rendered by ResourceList); keep the draft to retry.
    }
  }

  return (
    <Stack as="form" onSubmit={onSubmit}>
      <Field label="Title">
        <Input value={title} onChange={(event) => setTitle(event.target.value)} />
      </Field>
      <Field label="Status">
        <Select value={status} onChange={(event) => setStatus(event.target.value)}>
          <option value="open">open</option>
          <option value="doing">doing</option>
          <option value="done">done</option>
        </Select>
      </Field>
      <Button type="submit">Add</Button>
    </Stack>
  );
}

/** The tasks overview page: list, create, and soft-delete — the soft-delete trait made visible. */
export function TasksList() {
  const tasks = useTasks();
  return (
    <OverviewPage title="Tasks">
      <ResourceList
        resource={tasks}
        renderCreate={() => <NewTaskForm onAdd={tasks.add} />}
        renderItem={(task) => (
          <>
            <strong>{task.title}</strong> — {task.status}
          </>
        )}
        renderActions={(task) => (
          <Button
            variant="secondary"
            onClick={() => {
              void tasks.remove(task.id).catch(() => undefined);
            }}
          >
            Delete
          </Button>
        )}
      />
    </OverviewPage>
  );
}
