import { OverviewPage, ResourceList } from "@terpjs/react-core";

import { useProjects } from "./useProjects";

/** The projects overview page for the caller's tenant (tenancy is enforced by the backend). */
export function ProjectsList() {
  const projects = useProjects();
  return (
    <OverviewPage title={{ id: "projects.title", message: "Projects" }}>
      <ResourceList
        resource={projects}
        createPlaceholder={{ id: "projects.create", message: "New project name" }}
        renderItem={(project) => <strong>{project.name}</strong>}
      />
    </OverviewPage>
  );
}
