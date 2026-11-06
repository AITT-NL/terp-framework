import { Stack, Trans } from "@terpjs/react-core";

// The literals here are state tokens being compared, not copy: each expression
// evaluates to a boolean and neither operand is ever rendered. Hoisting them into
// variables above the JSX would say nothing truer and read worse.
export function Widget({ status }: { status: string }) {
  return (
    <Stack>
      {status === "paused" && <Trans id="widgets.paused" message="Paused" />}
      {status !== "paused" && <Trans id="widgets.live" message="Live" />}
    </Stack>
  );
}
