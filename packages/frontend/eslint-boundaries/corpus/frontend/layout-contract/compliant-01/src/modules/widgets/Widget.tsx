import { HubCard, HubPage } from "@terpjs/react-core";
export function Widget() {
  return (
    <HubPage title={{ id: "notes.title", message: "Notities" }}>
      <HubCard title={{ id: "notes.all", message: "Alle notities" }} to="/notes" />
    </HubPage>
  );
}
