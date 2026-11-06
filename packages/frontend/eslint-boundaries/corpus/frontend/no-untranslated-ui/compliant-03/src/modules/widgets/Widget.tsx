import { DetailList, Grid, Page } from "@terpjs/react-core";

// `columns` is a layout keyword here, not copy: Grid and DetailList take a column
// count or "auto", and nothing renders the word. A property that is not text is
// not in scope, whatever its value spells.
export function Widget() {
  return (
    <Page title={{ id: "widgets.title", message: "Widgets" }}>
      <Grid columns="auto" />
      <DetailList columns="auto" />
    </Page>
  );
}
