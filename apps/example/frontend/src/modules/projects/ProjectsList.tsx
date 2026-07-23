import { OverviewPage, ResourceList } from "@terpjs/react-core";

import { useProjects } from "./useProjects";

/** The projects overview page for the caller's tenant (tenancy is enforced by the backend). */
export function ProjectsList() {
  const projects = useProjects();
  return (
    <OverviewPage title="Projects">
      <ResourceList
        resource={projects}
        createPlaceholder="New project name"
        renderItem={(project) => <strong>{project.name}</strong>}
      />
    </OverviewPage>
  );
}
