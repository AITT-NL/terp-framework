import { Page } from "@terpjs/react-core";

export function Widget({ messageId }: { messageId: string }) {
  return <Page title={{ id: messageId, message: "Widgets" }} />;
}
