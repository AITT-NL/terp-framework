import { defineModuleManifest } from "@terp/contract";

import { FilesView } from "./FilesView";

// Dogfoods the files capability's frontend surface (ADR 0056/0057): the react-core
// FileUpload picker, the authenticated download helper, and a DataView over /files.
export const manifest = defineModuleManifest({
  name: "files",
  routes: [{ path: "/files", view: "FilesView" }],
  nav: [{ label: "Files", to: "/files", icon: "upload" }],
});

export const views = { FilesView };
