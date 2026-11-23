import { Button } from "@terpjs/react-core";
import styles from "./Widget.module.css";

// A spread carries the module class past the className check, onto a framework control.
export const Widget = () => <Button {...{ className: styles.board }} />;
