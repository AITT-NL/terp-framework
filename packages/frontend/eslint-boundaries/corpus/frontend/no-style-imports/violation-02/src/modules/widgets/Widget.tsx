import styles from "./Widget.module.css";

// The import is the sanctioned form; the stylesheet behind it reaches past its own classes.
export const Widget = () => <div className={styles.board} />;
