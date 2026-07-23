# `template/` — client repo skeleton (Phase 5)

A [copier](https://copier.readthedocs.io/) template for new Terp client applications: a
runnable full-stack repo with `create_app` wired to a base-profile control plane, a
discovered capability stack (auth · identity · users · access · audit), one example
module in the canonical five-slot shape, and a React frontend (Vite + `@terpjs/react-core`)
with a matching, auto-discovered module slot — plus CI, `AGENTS.md`, and an architecture
test.

## Use it

```bash
copier copy gh:AITT-NL/terp-framework/template ./my-app
cd my-app && uv sync
npm --prefix frontend install   # frontend deps
terp check                      # the architecture gate (== CI)
terp dev                        # run the API + frontend together
```

Inputs (see `copier.yml`): `project_name`, `project_slug`, `layout`. The rendered
sources live under `project/` (`_subdirectory: project`), so this README and the
top-level `AGENTS.md` stay out of the generated repo. `terp new module <name>` adds
further modules against the same shape.
