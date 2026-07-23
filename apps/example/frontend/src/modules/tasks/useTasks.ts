import { unwrap, useResource, useTerpClient } from "@terpjs/react-core";
import type { Resource } from "@terpjs/react-core";
import type { paths, components } from "../../api/schema";

type TaskRead = components["schemas"]["TaskRead"];

/** A tasks collection plus `remove` (soft-delete) and a multi-field `add` (title + status). */
export interface TasksResource extends Resource<TaskRead, string> {
  /** Soft-delete a task by id, then reload; the base query then hides the deleted row. */
  remove: (id: string) => Promise<void>;
  /** Create a task from a title + a status, then reload (the multi-field create form). */
  add: (title: string, status: string) => Promise<void>;
}

/**
 * The tasks data hook. Beyond list/create it exposes `remove` (soft-delete, made visible as the row
 * drops out of the list) and `add` (the multi-field create form's title + status).
 */
export function useTasks(): TasksResource {
  const client = useTerpClient<paths>();
  const resource = useResource<TaskRead, string>({
    list: async () => unwrap(await client.GET("/api/v1/tasks/", {})).items,
    create: async (title) => {
      unwrap(await client.POST("/api/v1/tasks/", { body: { title, status: "open" } }));
    },
  });
  const remove = async (id: string) => {
    await resource.mutate(async () => {
      unwrap(
        await client.DELETE("/api/v1/tasks/{task_id}", { params: { path: { task_id: id } } }),
      );
    });
  };
  const add = async (title: string, status: string) => {
    await resource.mutate(async () => {
      unwrap(await client.POST("/api/v1/tasks/", { body: { title, status } }));
    });
  };
  return { ...resource, remove, add };
}
