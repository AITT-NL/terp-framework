import { defineModuleManifest } from "@terp/contract";

import { TasksList } from "./TasksList";

export const manifest = defineModuleManifest({
  name: "tasks",
  routes: [{ path: "/tasks", view: "TasksList" }],
  nav: [{ label: "Tasks", to: "/tasks", icon: "check" }],
});

export const views = { TasksList };
