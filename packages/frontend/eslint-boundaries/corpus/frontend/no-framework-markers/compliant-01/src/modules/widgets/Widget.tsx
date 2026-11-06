import { Card, Text, Trans } from "@terpjs/react-core";

const title = { id: "widgets.summary.title", message: "Summary" };

export function Widget() {
  return (
    <Card title={title} data-testid="widget-summary">
      <Text>
        <Trans id="widgets.summary.empty" message="Nothing here yet." />
      </Text>
    </Card>
  );
}
