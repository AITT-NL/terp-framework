import styles from "./Widget.module.css";

// The module defines no such class, so the binding names nothing the stylesheet scopes.
export const Widget = () => <div className={styles.lane} />;
