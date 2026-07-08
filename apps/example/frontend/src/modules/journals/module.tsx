import { defineModuleManifest } from "@terp/contract";

import { JournalsList } from "./JournalsList";

export const manifest = defineModuleManifest({
  name: "journals",
  routes: [{ path: "/journals", view: "JournalsList" }],
  nav: [{ label: "Journals", to: "/journals", icon: "book" }],
});

export const views = { JournalsList };
