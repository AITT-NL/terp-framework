import { Button } from "@terpjs/react-core";
import styles from "./Widget.module.css";

let stash;

// The test of a valid conditional stores the binding; the spread then carries it to a control.
export const Widget = ({ on }) => (
  <>
    <div className={(stash = styles, on) ? styles.active : styles.board} />
    <Button {...{ className: stash.board }} />
  </>
);
