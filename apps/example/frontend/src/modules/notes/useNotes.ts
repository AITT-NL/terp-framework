import { unwrap, useResource, useTerpClient } from "@terp/react-core";
import type { Resource } from "@terp/react-core";
import type { paths, components } from "../../api/schema";

type NoteRead = components["schemas"]["NoteRead"];

/**
 * The notes data hook: lists notes and creates one from a title, over the app's own typed contract
 * client. A view calls `useNotes()` and renders `items` / calls `create` — the fetching, loading and
 * error state live here (via `useResource`), not in the view.
 */
export function useNotes(): Resource<NoteRead, string> {
  const client = useTerpClient<paths>();
  return useResource<NoteRead, string>({
    list: async () => unwrap(await client.GET("/api/v1/notes/", {})).items,
    create: async (title) => {
      unwrap(await client.POST("/api/v1/notes/", { body: { title, body: "" } }));
    },
  });
}
