import { Link, Trans } from "@terpjs/react-core";
export function Widget() {
  return <Link to="/notes"><Trans id="widget.notes" message="Notes" /></Link>;
}
