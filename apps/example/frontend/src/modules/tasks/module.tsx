import { defineModuleManifest } from "@terpjs/contract";

import { TasksList } from "./TasksList";

export const manifest = defineModuleManifest({
  name: "tasks",
  routes: [{ path: "/tasks", view: "TasksList" }],
  nav: [{ label: { id: "tasks.title", message: "Tasks" }, to: "/tasks", icon: "check" }],
});

export const views = { TasksList };
