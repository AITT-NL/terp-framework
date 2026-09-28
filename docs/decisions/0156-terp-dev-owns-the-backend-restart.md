# 0156 — `terp dev` owns the backend restart

- **Status:** Accepted and implemented. `terp dev` runs uvicorn without `--reload` and
  restarts it itself when a Python source of the app changes. Held by
  `tests/architecture/test_cli_dev.py`.
- **Date:** 2026-09-27
- **Relates:** [ADR 0108](0108-a-stream-has-no-end-so-the-shutdown-needs-one.md) (the
  graceful-shutdown bound `terp dev` passes to uvicorn),
  [ADR 0141](0141-the-gate-scans-every-deployable-not-only-the-mounted-one.md) (the declaration that
  now also says what a save restarts)

---

## Context

`terp dev` ran the API as `uvicorn <app> --reload`. On Windows, uvicorn's reloader
restarts its worker by sending it a console Ctrl+C (`os.kill(pid, CTRL_C_EVENT)`) and then
waiting for the worker to exit, with no time limit.

Started from something that is not an interactive console — an agent's shell tool, an
editor task, a workbench driving the app — that signal never stopped the worker. Measured on
this repository's own tooling: after an edit the reloader logged
`WatchFiles detected changes … Reloading...` and nothing after it, and the old worker went
on answering every request with the old code. Four edits in a row, four misses. Three ways of
giving the worker a console it could be signalled through were tried and none changed the
result: a hidden console of its own (`CREATE_NO_WINDOW`), a new console with its window
hidden (`CREATE_NEW_CONSOLE`), and re-enabling Ctrl+C handling in the reloader process. The
exact reason the event is not delivered was not pinned down, and this decision does not
depend on it.

The design centre of this framework is an app built by an agent, and on Windows that agent
runs `terp dev` from exactly the kind of process where the reload does not happen. A dev loop
that silently serves stale code is worse than one that fails: every observation the agent
makes afterwards is of a program that no longer exists.

Stopping processes had a second Windows defect of the same kind. `npm` resolves to
`npm.cmd`, so the frontend process `terp dev` started was `cmd.exe`, with Vite in a node
process beneath it. `terminate()` ends `cmd.exe` and leaves the process beneath it running
— measured with a `cmd /c` child, the shape `npm.cmd` has — so Vite kept the web port and the
next `terp dev` could not bind it.

## Decision

**`terp dev` restarts the backend itself, by means that need no console.**

- The backend runs as plain `uvicorn <app>`. The supervisor loop `terp dev` already ran
  (polling the servers) also takes a snapshot of the backend's Python sources on every poll,
  and when one is added, changed or removed it stops the backend and starts it again.
- **What is watched** is the app's own package plus every package
  `[tool.terp.arch] app_packages` declares. This is the declaration ADR 0141 made the single
  answer to "what is the application", so the scope the gate scans is the scope a save
  restarts. It is not the project root, which `--reload` watched and which holds
  `node_modules` and the virtualenv. It is not a declared companion either, because
  `create_app` does not mount one.
- **How it stops a process:** on Windows, `taskkill /T /F` on the process `terp dev`
  started, which ends the whole tree and needs no console; elsewhere, SIGTERM, which uvicorn
  honours within its graceful-shutdown bound. A process still running past that bound plus
  a margin is killed.
- **When the backend dies on its own** — a save that leaves a module half-written, so the
  import fails — it is waited for, not given up on, and the next save starts it again. That
  is the behaviour `--reload` had. The frontend exiting still ends the session.
- **Ctrl+C is an ordinary stop.** Every process is stopped on the way out, however the
  session ends.
- **`terp dev`'s own lines are flushed** as they are written. A pipe is block-buffered, so
  a line saying the backend restarted used to sit in the buffer until the process ended, and
  a stopped process's buffer is lost.

A stat walk rather than an OS file watcher: the watched paths are the app's own packages,
the walk has no dependency, and it behaves the same on every platform. The cost is up to one
poll interval (half a second) between a save and the restart.

## Consequences

- An agent on Windows gets a dev loop that restarts. Launched the same way, uvicorn's
  reloader missed every edit, while `terp dev` served each edit within about a second, and
  the port was free once it stopped.
- The restart is not graceful on Windows. A lifespan shutdown hook does not run when a
  development backend is restarted there. That trade is deliberate: on a development
  machine, a restart that happens is worth more than a clean exit.
- Python code outside the declared packages no longer restarts the backend when it changes.
  Code the API imports that is not in a declared package is also code the gate does not
  scan; the fix for both is to declare it.
- Running uvicorn directly with `--reload` is unchanged and still documented for anyone
  who prefers the servers apart. The template README says where it does not restart.
