import { unwrap, useResource, useTerpClient } from "@terpjs/react-core";
import type { Resource } from "@terpjs/react-core";
import type { paths, components } from "../../api/schema";

type ProjectRead = components["schemas"]["ProjectRead"];

/**
 * The projects data hook. Projects are tenant-scoped, so the list only ever returns the caller's
 * tenant — the tenancy predicate lives in the base query, not here; the hook just fetches.
 */
export function useProjects(): Resource<ProjectRead, string> {
  const client = useTerpClient<paths>();
  return useResource<ProjectRead, string>({
    list: async () => unwrap(await client.GET("/api/v1/projects/", {})).items,
    create: async (name) => {
      unwrap(await client.POST("/api/v1/projects/", { body: { name } }));
    },
  });
}
