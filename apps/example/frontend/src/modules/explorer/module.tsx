import { defineModuleManifest } from "@terp/contract";

import { DevicesExplorer } from "./DevicesExplorer";
import { NotesExplorer } from "./NotesExplorer";

// The DataView showcase module: one page per repository type — the in-memory
// (client-side) repository over a static data set, and the HTTP (server-side)
// repository over the notes endpoint.
export const manifest = defineModuleManifest({
  name: "explorer",
  routes: [
    { path: "/explorer/devices", view: "DevicesExplorer" },
    { path: "/explorer/notes", view: "NotesExplorer" },
  ],
  nav: [
    { label: "Devices (DataView)", to: "/explorer/devices", icon: "database" },
    { label: "Notes (DataView)", to: "/explorer/notes", icon: "database" },
  ],
});

export const views = { DevicesExplorer, NotesExplorer };
