# The reference app

The public-safe stand-in for a real client application, in every lane that needs one:
this repository's CI and any downstream test lane. A real client app may
never run in any of them, because it belongs to someone and this repository is public.
So this one is built to carry, in kind, what such an app has and the template alone does
not: many services on the backend image, a scheduler that must never turn readiness red,
and a third source root shipped beside the app.

It is small on purpose: one module (`notices`) with two records, and each capability
used once, for real, through the platform's own seam.

## How it is built

It is not committed as a rendered tree. A committed render would be a second definition
of the template, frozen at the commit it was taken from, version pins included. It is
produced the way a client repository is, every time:

```bash
python tools/render_reference_app.py ../reference-app    # Python 3.13+ and uvx; nothing else
```

1. `copier copy` of `template/` with [`answers.yml`](answers.yml) (blank layout, file
   storage on);
2. the rendered `pyproject.toml` grown at named anchors: four more `terp-cap-*`
   distributions at the template's own pin, the companion root, and import-linter;
3. [`overlay/`](overlay) copied over the render: the module, the companion, their tests,
   the stack check, and the files the app owns or has changed.

The result has a client repository's shape: `.copier-answers.yml`, its own CI workflow,
Dockerfiles whose build context is the project directory, and nothing that reaches back
into this repository. Before a release is on the package index, install against locally
built wheels with `UV_FIND_LINKS`, as template acceptance does.

## What each capability exercises

| Capability | In the app | Proven by |
|---|---|---|
| **Worker** (`terp-cap-outbox`) | `app/main.py` wires `OutboxJobQueue`, so every job is a row committed with the write that caused it. The `worker` service runs `terp jobs worker --forever` in both compose profiles. | The suite drains the outbox with `OutboxWorker`; the stack check waits for the mail and the snapshot only the worker can produce. |
| **Scheduler** (`terp-cap-scheduler-apscheduler`) | `control_plane/schedules.py` declares `notices.snapshot.hourly`. The `scheduler` service runs `terp jobs scheduler`, with no healthcheck and nothing depending on it, so it stays out of readiness. | The suite fires a tick through `trigger_schedule` and registers the cron with APScheduler; CI reads the registration from the scheduler's log. |
| **File storage** (`terp-cap-files`) | The snapshot job stores what the upstream returned through `FileService`; `Snapshot.file_id` is a declared `FileRef`; one `files-data` volume is shared by the API and the worker. | The suite reads the bytes back with `load_for`; the stack check downloads them from `/api/v1/files/{id}/content` and compares the size. |
| **Mail** (`terp-cap-mail`) | `configure_mail` reads the relay from `MAIL_FROM` / `SMTP_*`; a new notice is mailed from `NoticeService._after_write`. In development the relay is the `mailcatcher` service (Mailpit), which is what `terp env init` writes from the declared defaults. | The suite captures the delivery with `CapturingMailTransport`; the stack check finds the mail in the catcher's inbox. |
| **Egress** (`terp-cap-egress`) | `app/modules/notices/upstream.py` declares one `EgressPolicy`: `example.com` (the domain reserved for documentation), HTTPS only, bounded. The snapshot job makes the one call. | The suite swaps the transport and keeps the policy, and proves every other host and plain HTTP are refused before a lookup; the stack check makes the real call from the worker container. |
| **Companion root** | `monitor/` is declared in `[tool.terp.arch] companions`, fenced from `app` by import-linter contracts, built into the wheel, and runs as the `monitor` service with its own source mount. It logs the outbox backlog and warns once due work has gone stale. | `terp check` scans it as a companion root; `tests/test_monitor.py`; CI reads the backlog line from its log. |

`POST /api/v1/notices/snapshots/` asks for a snapshot now, so a lane can drive the
egress and storage path over HTTP instead of waiting for the hour.

Deliberately absent: realtime and Redis, single sign-on, domain events and a frontend
screen for the module. A capability the platform does not ship yet is not imitated here;
it joins the app when it ships.

## How each lane uses it

- **This repository's CI** runs it as the `reference` variant of `template-acceptance`
  (`.github/workflows/ci.yml`): render, the app's own suite, `ruff`, `deptry` and `terp
  check` against staged wheels, its frontend built against packed tarballs, `terp verify
  --profile quick`, and then its whole development stack, driven by
  `scripts/check_stack.py`. A change to the framework or the template that breaks any of
  it is red on the pull request that makes it. `tests/architecture/test_reference_app.py`
  holds what needs neither copier nor Docker.
- **A downstream harness** (a deploy tool's own CI, for one) renders it from the
  framework commit it already pins, into a fresh working directory it initialises as a
  repository, and runs a scripted change, its gate, its publish step and a Test deploy
  against that, in place of a client's app. No new repository and no second pin: the app moves with the framework.
- **A deployment test environment** deploys its production profile, `docker-compose.prod.yml`: the
  worker, the scheduler and the companion on the backend image beside the API. The file is
  the generator's render of the reference shape (the `grown` golden sample of ADR 0187),
  kept as the app's own under `"build": "own"`, and a test holds the two equal. That
  profile has no mail catcher: the relay is external, and `MAIL_FROM` and `SMTP_HOST` are
  required there (`requiredIn` production). Its `.app.env` names an encrypted relay
  (`SMTP_SECURITY` `starttls` or `tls`; a production boot refuses `none` and refuses no
  relay at all) and a `JOB_SYSTEM_ACTOR_ID`, and the host needs outbound HTTPS to
  `example.com`. Outside production that relay is a mail catcher offering TLS, never a real
  one, and `SMTP_CA_FILE` names the authority that issued its certificate, so the app
  verifies it as it verifies any relay (`terp guide mail`). `scripts/check_stack.py --api …
  --mailpit …` drives it wherever the relay's inbox can be read.

## Running it yourself

```bash
python tools/render_reference_app.py ../reference-app && cd ../reference-app
uv sync && uv run pytest
uv run terp ports assign && uv run terp env init
uv run python scripts/check_stack.py --workbench
```

`--workbench` is the whole procedure: it starts the development stack (`api`, `worker`,
`scheduler`, `monitor`, `mailcatcher`), seeds it, drives a notice's mail and a snapshot
through it, and checks the scheduler's and the companion's logs. Against a stack started
some other way, `--api URL --mailpit URL` runs the HTTP steps alone. Caught mail is in
the inbox at the address `docker compose port mailcatcher 8025` prints.

## Known gaps

- The suite takes `terp_db_url`, so it runs on PostgreSQL wherever `TERP_TEST_POSTGRES_URL`
  names a server, as the app's own CI workflow provides. `template-acceptance` has no
  server, so there the PostgreSQL half skips, and the stack check is what runs the app on
  PostgreSQL.

## Changing it

- Edit `overlay/`, never a render. A new migration is made the usual way in a render
  (`uv run terp migrate make notices`) and its revision copied back into the overlay.
- Some overlay files are copies of files the template still owns: `app/main.py`,
  `control_plane/__init__.py`, both compose files and `.app.env.example`.
  [`template-baseline.json`](template-baseline.json) records the digest of each template
  source. When the template changes one, the gate fails and names it: carry the change
  into the overlay copy (or decide it does not apply), then run
  `python tools/render_reference_app.py --record-baseline`. That is the `copier update`
  conflict every client app meets, met here first.
- `.app.env.example` is generated: after changing `environment.schema.json`, run
  `uv run terp env example` in a render and copy the file back.
