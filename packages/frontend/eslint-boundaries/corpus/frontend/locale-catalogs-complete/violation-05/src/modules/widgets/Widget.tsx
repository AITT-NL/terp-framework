import { Page } from "@terpjs/react-core";

// A descriptor factory. Every call through it carries its copy in a call's
// arguments, where the catalog inventory never looks: the English entry for
// "widgets.title" is missing, and without refusing the factory nothing here
// would report it.
const msg = (id: string, message: string) => ({ id, message });

export function Widget() {
  return <Page title={msg("widgets.title", "Onderdelen")} />;
}
