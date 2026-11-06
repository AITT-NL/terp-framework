import { Page } from "@terpjs/react-core";

interface Notice {
  id: string;
  text: string;
}

// Business records keep their id/message shape without a descriptor factory.
// Built from the record, from a destructured object, or keyed into data, their
// values are data rather than an author's copy under another name, so none of
// these is refused.
export const toMessage = (notice: Notice) => ({ id: notice.id, message: notice.text });
export const toMessages = (rows: { id: string; message: string }[]) =>
  rows.map(({ id, message }) => ({ id, message }));
export const labelled = (ids: string[], labels: Record<string, string>) =>
  ids.map((id) => ({ id, message: labels[id] }));

export function Widget() {
  return <Page title={{ id: "widgets.title", message: "Widgets" }} />;
}
