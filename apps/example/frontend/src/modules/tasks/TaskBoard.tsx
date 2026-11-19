import { Page, Trans, useUiText } from "@terpjs/react-core";

import styles from "./TaskBoard.module.css";
import { useTasks } from "./useTasks";

const lanes = [
  { status: "open", label: { id: "tasks.status.open", message: "Open" } },
  { status: "doing", label: { id: "tasks.status.doing", message: "Doing" } },
  { status: "done", label: { id: "tasks.status.done", message: "Done" } },
];

export function TaskBoard() {
  const tasks = useTasks();
  const text = useUiText();
  // Status is free text in the API. Preserve rows with an unfamiliar status.
  const groups = lanes.map((lane) => ({
    ...lane,
    items: tasks.items.filter((task) => task.status === lane.status),
  }));
  const other = tasks.items.filter((task) => !lanes.some((lane) => lane.status === task.status));
  if (other.length) {
    groups.push({ status: "other", label: { id: "tasks.board.other", message: "Other" }, items: other });
  }

  return (
    <Page title={{ id: "tasks.board", message: "Planning board" }}
      isLoading={tasks.loading} error={tasks.cause ?? tasks.error}>
      <div className={styles.board}>
        {groups.map(({ status, label, items }) => (
          <section key={status} className={styles.lane} aria-labelledby={`lane-${status}`}>
            <h2 id={`lane-${status}`} className={styles.heading}>{text(label)}</h2>
            {items.length ? (
              <ul className={styles.cards}>
                {items.map((task) => <li key={task.id} className={styles.card}>{task.title}</li>)}
              </ul>
            ) : <p><Trans id="tasks.board.empty" message="No tasks" /></p>}
          </section>
        ))}
      </div>
    </Page>
  );
}
