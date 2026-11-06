import { Page, Trans } from "@terpjs/react-core";

const title = { id: "widgets.title", message: "Widgets" };

export function Widget() {
  return (
    <Page title={title}>
      <Trans id="widgets.empty" message="Nothing here yet." />
    </Page>
  );
}
