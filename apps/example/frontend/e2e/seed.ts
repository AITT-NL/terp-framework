// This app's own seeded content and module UI strings (see ../../app/seed.py and the module
// pages under ../src/modules). These are app data, not framework constants — which is why they
// live here in the app's e2e suite rather than in @terpjs/conformance, which stays domain-agnostic.

export const NOTES = {
  link: "Notes",
  createPlaceholder: "New note title",
  seedText: ["Welcome to Terp", "Try editing me"],
};

export const TASKS = {
  link: "Tasks",
  seedText: ["Explore the audit log", "Ship something"],
};

export const PROJECTS = {
  link: "Projects",
  seedText: ["Acme launch", "Internal tooling"],
};

export const JOURNALS = {
  link: "Journals",
  seedText: ["Day one"],
};
