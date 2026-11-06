import { Text, Trans } from "@terpjs/react-core";

export function Widget() {
  return (
    <div data-terp="card">
      <Text>
        <Trans id="widgets.summary.empty" message="Nothing here yet." />
      </Text>
    </div>
  );
}
