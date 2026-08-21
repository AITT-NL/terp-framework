import { Button, Field, Input, OverviewPage, ResourceList, Select, Stack } from "@terpjs/react-core";
import { useState } from "react";
import type { FormEvent } from "react";

import type { SelectOption } from "@terpjs/react-core";

import { useTasks } from "./useTasks";

/** The task lifecycle, as a closed set — the thing the Select is checked against. */
type TaskStatus = "open" | "doing" | "done";

/**
 * The status choices as data.
 *
 * Typed `SelectOption<TaskStatus>[]`, which is what makes the list and the state agree: a
 * fourth row spelled "dong" is a typecheck error here rather than an option the app can
 * select and the backend rejects. Before `Select` took an options list this was three
 * hand-written `<option>` elements plus `setStatus(event.target.value)` — the value arriving
 * as a bare `string`, so nothing connected the markup to the union at all.
 */
const TASK_STATUSES: SelectOption<TaskStatus>[] = [
  { value: "open", label: "open" },
  { value: "doing", label: "doing" },
  { value: "done", label: "done" },
];

/** A multi-field create form (title + status), composed from the shared form primitives. */
function NewTaskForm({ onAdd }: { onAdd: (title: string, status: string) => Promise<void> }) {
  const [title, setTitle] = useState("");
  const [status, setStatus] = useState<TaskStatus>("open");

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
        <Select options={TASK_STATUSES} value={status} onValueChange={setStatus} />
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
