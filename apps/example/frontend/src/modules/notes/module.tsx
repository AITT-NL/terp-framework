import { defineModuleManifest } from "@terp/contract";

import { NotesList } from "./NotesList";

// A module is discovered by dropping this file in — it exports `manifest` and `views`,
// and renderTerpApp's import.meta.glob wires it with no central registration.
export const manifest = defineModuleManifest({
  name: "notes",
  routes: [{ path: "/", view: "NotesList" }],
  nav: [{ label: "Notes", to: "/", icon: "clipboard" }],
});

export const views = { NotesList };
