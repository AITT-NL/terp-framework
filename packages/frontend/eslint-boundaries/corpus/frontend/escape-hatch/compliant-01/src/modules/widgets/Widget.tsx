import { Trans } from "@terpjs/react-core";

export function Widget() {
  // terp-allow-token-styled-elements: native button needed for a browser extension host
  return <button><Trans id="widget.save" message="Save" /></button>;
}
