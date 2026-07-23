import { unwrap, useResource, useTerpClient } from "@terpjs/react-core";
import type { Resource } from "@terpjs/react-core";
import type { paths, components } from "../../api/schema";

type JournalRead = components["schemas"]["JournalRead"];

/** A journals collection plus a multi-field `add` (title + a multi-line entry) for the create form. */
export interface JournalsResource extends Resource<JournalRead, string> {
  /** Create a journal from a title + entry, then reload. */
  add: (title: string, entry: string) => Promise<void>;
}

/**
 * The journals data hook. Journals carry the ownership trait (`owner_id`): the backend stamps the
 * creator as owner and only the owner may edit or delete. `add` creates from the multi-field form.
 */
export function useJournals(): JournalsResource {
  const client = useTerpClient<paths>();
  const resource = useResource<JournalRead, string>({
    list: async () => unwrap(await client.GET("/api/v1/journals/", {})).items,
    create: async (title) => {
      unwrap(await client.POST("/api/v1/journals/", { body: { title, entry: "", visibility: "shared" } }));
    },
  });
  const add = async (title: string, entry: string) => {
    await resource.mutate(async () => {
      unwrap(await client.POST("/api/v1/journals/", { body: { title, entry, visibility: "shared" } }));
    });
  };
  return { ...resource, add };
}
