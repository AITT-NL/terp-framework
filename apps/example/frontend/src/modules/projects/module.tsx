import { defineModuleManifest } from "@terpjs/contract";

import { ProjectsList } from "./ProjectsList";

export const manifest = defineModuleManifest({
  name: "projects",
  routes: [{ path: "/projects", view: "ProjectsList" }],
  nav: [{ label: "Projects", to: "/projects", icon: "briefcase" }],
});

export const views = { ProjectsList };
