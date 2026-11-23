import { Card } from "@terpjs/react-core";
import styles from "./Widget.module.css";

// Ink set on an element that holds a Card is inherited by the Card's own title.
export const Widget = () => (
  <section className={styles.lane}>
    <Card />
  </section>
);
