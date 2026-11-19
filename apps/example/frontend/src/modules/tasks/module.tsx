import { defineModuleManifest } from "@terpjs/contract";

import { TaskBoard } from "./TaskBoard";
import { TasksList } from "./TasksList";

export const manifest = defineModuleManifest({
  name: "tasks",
  routes: [
    { path: "/tasks", view: "TasksList" },
    { path: "/tasks/board", view: "TaskBoard" },
  ],
  nav: [
    { label: { id: "tasks.title", message: "Tasks" }, to: "/tasks", icon: "check" },
    { label: { id: "tasks.board", message: "Planning board" }, to: "/tasks/board", icon: "grid" },
  ],
});

export const views = { TasksList, TaskBoard };
