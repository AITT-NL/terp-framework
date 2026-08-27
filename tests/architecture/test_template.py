"""Template skeleton integrity — the copier client-app template scaffolds a real app.

Validates the structure deterministically (no copier install required): the composition
root, the control plane, the home module per layout preset, and the generated
`AGENTS.md`. The template deliberately ships NO pre-built domain module — the first
module is created on demand (`terp new module <name>`), whose five-slot shape is
exercised by test_cli_scaffold.py against every architecture rule.
"""

from __future__ import annotations

import json
import pathlib
import re

_TEMPLATE = pathlib.Path(__file__).resolve().parents[2] / "template"
_PROJECT = _TEMPLATE / "project"
_CODEGEN = (
    pathlib.Path(__file__).resolve().parents[2]
    / "packages/frontend/contract/src/routes-codegen.js"
)
_REACT_CORE = (
    pathlib.Path(__file__).resolve().parents[2] / "packages/frontend/react-core/src"
)


def _shipped_palettes() -> list[str]:
    """Every theme react-core ships, minus ``system``.

    Read from the source of truth rather than restated here, because a list
    written twice is the defect these gates exist to catch. ``system`` is not a
    palette — it is "follow the platform" — so it is dropped: the docs may
    mention it, and must not be required to name it as one of the painted sets.
    """
    source = (_REACT_CORE / "themes.ts").read_text(encoding="utf-8")
    block = re.search(r"THEMES:\s*readonly Theme\[\]\s*=\s*\[(.*?)\]", source, re.DOTALL)
    assert block, "could not locate THEMES in react-core/src/themes.ts"
    names = re.findall(r'"([a-z]+)"', block.group(1))
    assert len(names) > 2, f"THEMES parsed to {names} — the regex stopped matching"
    return [name for name in names if name != "system"]



def test_copier_config_declares_inputs_and_subdirectory() -> None:
    config = (_TEMPLATE / "copier.yml").read_text()
    assert "_subdirectory: project" in config
    for var in ("project_name", "project_slug", "layout"):
        assert var in config
    # The template ships no pre-built domain module: the first module is created
    # on demand (`terp new module <name>`), named after the actual domain — so
    # nothing generic exists to rename or delete.
    assert "module_name" not in config


def test_copier_declares_the_layout_presets_and_capability_toggles() -> None:
    # The create wizard's deterministic surface: four layout presets (all
    # module-less home shapes; blank is the default) and the capability
    # toggles whose wiring the template renders end-to-end. Every toggle here
    # must stay provably green in the template-acceptance matrix.
    config = (_TEMPLATE / "copier.yml").read_text()
    for choice in ("blank", "hub", "process", "portal"):
        assert f": {choice}" in config
    assert "default: blank" in config
    # `list` survives only as a LEGACY answers-file alias (copier update
    # validates recorded answers against the choices), never as an offering.
    assert "(legacy) Single-list" in config
    for toggle in ("use_files", "use_sso", "use_events", "use_realtime"):
        assert toggle in config


def test_runnable_app_skeleton_present() -> None:
    main = (_PROJECT / "app" / "main.py.jinja").read_text()
    assert "create_app(" in main
    assert (_PROJECT / "control_plane" / "__init__.py").exists()
    assert (_PROJECT / "pyproject.toml.jinja").exists()
    assert (_PROJECT / "AGENTS.md.jinja").exists()


def test_generated_app_refuses_to_serve_against_a_wrong_schema() -> None:
    # Every generated app installs the fail-closed migration boot guard in
    # production, not just the example app: behind, missing, or holding a revision
    # the code no longer defines all fail at boot rather than at the first request
    # that touches the affected table.
    main = (_PROJECT / "app" / "main.py.jinja").read_text()
    assert "migration_check=" in main
    assert "assert_migrations_current" in main
    assert "app_root=pathlib.Path(__file__).resolve().parent" in main
    assert "get_settings().is_production" in main  # development still auto-applies


def test_project_records_copier_answers_for_upgrades() -> None:
    # The answers file is what makes `copier update` — and the Studio's upgrade
    # flow plus its template-version stamping — possible: without it, a rendered
    # project cannot be re-rendered against a newer template.
    answers = _PROJECT / "{{ _copier_conf.answers_file }}.jinja"
    assert answers.exists()
    assert "_copier_answers" in answers.read_text()
    # It must be committed (never git-ignored) so `copier update` can read it.
    assert ".copier-answers" not in (_PROJECT / ".gitignore").read_text()


def test_project_routes_claude_code_to_the_shared_agent_instructions() -> None:
    # AGENTS.md is the single source of agent instructions; Claude Code reads
    # CLAUDE.md, so the template ships one that imports AGENTS.md (`@path` is
    # Claude Code's memory-import syntax) instead of forking the content.
    claude = _PROJECT / "CLAUDE.md"
    assert claude.exists()
    assert "@AGENTS.md" in claude.read_text()


def test_project_ships_ci_and_hatch_packaging() -> None:
    # The generated repo claims `terp verify` == CI, so a CI workflow must ship and it
    # must DELEGATE (test_cli_verify.py holds what the profile then owes it); and the
    # hatchling build backend needs an explicit `app` package to build.
    ci = (_PROJECT / ".github" / "workflows" / "ci.yml.jinja").read_text()
    assert "terp verify --profile full" in ci
    # The api-docs drift gate is a release-profile check the merge bar opts into, so a
    # committed docs/ contract cannot silently fall behind the installed kernel.
    assert "--only api-docs-drift" in ci
    pyproject = (_PROJECT / "pyproject.toml.jinja").read_text()
    assert 'packages = ["app", "control_plane"]' in pyproject


def test_template_ships_no_prebuilt_domain_module() -> None:
    # The whole point of the retirement: no `{{ module_name }}` trees, backend or
    # frontend — an app is born with the platform surface only, and its first
    # module arrives via `terp new module <name>` with the right domain name.
    app_modules = [p.name for p in (_PROJECT / "app" / "modules").iterdir()]
    assert app_modules == ["__init__.py"]
    frontend_modules = sorted(
        p.name for p in (_PROJECT / "frontend" / "src" / "modules").iterdir()
    )
    assert frontend_modules == ["home"]


def test_layout_presets_render_a_home_module() -> None:
    # Every layout gets the frontend-only `home` module owning "/": hub/process/
    # portal a HubPage of PLACEHOLDER cards (no module exists yet, so they point
    # at "/" until the first module lands), blank a welcome page.
    home = _PROJECT / "frontend" / "src" / "modules" / "home"
    manifest = (home / "module.tsx.jinja").read_text()
    assert "defineModuleManifest(" in manifest
    assert 'path: "/"' in manifest
    view = (home / "Home.tsx.jinja").read_text()
    # Hub/process/portal: a HubPage of cards, linking through the stack's router Link.
    assert "HubPage" in view
    assert "HubCard" in view
    assert 'import { Link } from "@tanstack/react-router"' in view
    assert "renderLink=" in view
    assert "Werkvoorraad" in view
    assert "Mijn overzicht" in view
    # Sidebar label and rendered page title share the same layout-dependent source.
    assert "Werkvoorraad" in manifest
    assert "Mijn overzicht" in manifest
    assert "{{ project_name }}" in manifest
    assert 'label: "Home"' not in manifest
    # The placeholder cards must not reference a module that does not exist.
    assert "module_name" not in view
    # Blank: a plain archetype-framed welcome page pointing at `terp new module`.
    assert "Page" in view
    # And its prose goes through the primitives, not bare elements. Not tidiness: app modules
    # may not write `style` or `className`, and a bare <p> or <code> carries no `data-terp` for
    # any rule to reach — so bare prose in the generated starter is text a generated app can
    # never theme, and this file was the framework's own example of it.
    assert "<Text" in view and "<Code" in view
    # Comments stripped first, or the file's own explanation of this rule breaks it — which is
    # exactly what happened when the explanation named the two elements. Prose about a scan is
    # not exempt from the scan.
    view_code = re.sub(r"(?m)^\s*//.*$", "", view)
    assert "<p>" not in view_code and "<code>" not in view_code
    assert "terp new module" in view
    assert "style={{" not in view


def test_frontend_template_ships_checked_complete_app_locales() -> None:
    declaration = json.loads(
        (_PROJECT / "frontend" / "i18n.json.jinja").read_text(encoding="utf-8")
    )
    assert declaration["sourceLocale"] == "nl"
    assert set(declaration["locales"]) == {"nl", "en"}
    english = declaration["locales"]["en"]["messages"]
    assert english and all(value.strip() for value in english.values())

    main = (_PROJECT / "frontend" / "src" / "main.tsx.jinja").read_text(
        encoding="utf-8"
    )
    assert 'import i18n from "../i18n.json"' in main
    assert "defineAppLocales(i18n" in main
    assert "sourceLocale: i18n.sourceLocale" in main
    assert 'const APP_TITLE = "{{ project_name }}"' in main
    assert "title: APP_TITLE" in main
    assert 'title: "{{ project_name }}"' not in main

    home = (_PROJECT / "frontend" / "src" / "modules" / "home")
    authored = "\n".join(
        (home / filename).read_text(encoding="utf-8")
        for filename in ("Home.tsx.jinja", "module.tsx.jinja")
    )
    ids = set(re.findall(r'id:\s*"([^"]+)"|id="([^"]+)"', authored))
    flattened = {left or right for left, right in ids}
    assert flattened <= set(english), "starter UiText ids missing from the English target"

    agents = (_PROJECT / "AGENTS.md.jinja").read_text(encoding="utf-8")
    assert "frontend/i18n.json" in agents
    assert "<Trans id message />" in agents
    assert "every non-source locale" in agents


def test_capability_toggles_wire_the_composition_root() -> None:
    # A toggled capability is a dependency AND its composition-root wiring — never a
    # half-mounted dep. Files rides discovery; SSO/events need explicit seams.
    pyproject = (_PROJECT / "pyproject.toml.jinja").read_text()
    for dep in (
        "terp-cap-files",
        "terp-cap-oidc",
        "terp-cap-eventbus",
        "terp-cap-realtime",
    ):
        assert dep in pyproject
    main = (_PROJECT / "app" / "main.py.jinja").read_text()
    assert "if use_events %}" in main
    assert "event_dispatcher=dispatch_in_process" in main
    assert "if use_sso %}" in main
    assert "oidc_module" in main
    auth = (_PROJECT / "app" / "auth.py.jinja").read_text()
    assert "build_oidc_module" in auth
    # SSO is configuration-enabled: unset OIDC_* leaves the module None (app boots SSO-off);
    # the compose workbench forwards the same variables into the api container.
    assert 'os.environ.get("OIDC_ISSUER", "")' in auth
    main_tsx = (_PROJECT / "frontend" / "src" / "main.tsx.jinja").read_text()
    assert 'label: { id: "auth.sso.label", message: "SSO" }' in main_tsx
    env_example = (_PROJECT / ".env.example.jinja").read_text()
    assert "OIDC_ISSUER" in env_example
    compose = (_PROJECT / "docker-compose.yml.jinja").read_text()
    assert "OIDC_ISSUER: ${OIDC_ISSUER:-}" in compose
    # Uploads survive container rebuilds (the files cap's default local profile).
    assert "files-data:/app/var/files" in compose
    # The generated AGENTS.md tells the agent what was selected and wired.
    agents = (_PROJECT / "AGENTS.md.jinja").read_text()
    assert "This project's selections" in agents


def test_docs_teach_venv_correct_commands() -> None:
    # Agents copy literal commands, and a fresh checkout has `terp`/`python` only in
    # the project `.venv` — never on PATH. A bare `terp ...` therefore fails (and on
    # Windows a bare `python` hits the Store stub), which a coding agent misreads as
    # "Python is not installed". Every command the generated docs teach must run
    # through `uv run`, which resolves the project venv from anywhere.
    bare_terp = re.compile(
        r"(?<!uv run )\bterp (?:guide|check|dev|new|inspect|migrate|openapi|routes|docker|user)\b"
    )
    for doc in ("AGENTS.md.jinja", "README.md.jinja"):
        text = (_PROJECT / doc).read_text()
        assert not bare_terp.findall(text), f"{doc} teaches bare `terp` commands"
    agents = (_PROJECT / "AGENTS.md.jinja").read_text()
    assert "uv run terp check" in agents
    # ...and the definition of done spans BOTH halves of the gate — mirroring
    # exactly what the generated CI runs: an agent that only runs `terp check`
    # can ship a frontend that fails typecheck (a blank page at runtime) or a
    # module that is never mounted (only pytest catches that) while declaring
    # success.
    assert "Definition of done" in agents
    assert "uv run pytest" in agents
    assert "npm --prefix frontend run typecheck" in agents
    assert "npm --prefix frontend run lint" in agents
    assert "npm --prefix frontend run build" in agents
    assert "Runtime environment variables" in agents
    assert "environment.schema.json" in agents
    assert '"format": "secret"' in agents
    assert "Do not create/edit `.app.env`" in agents
    assert "Never add an opt-out marker or raise an escape-hatch budget" in agents
    assert "leave the check red" in agents
    assert "no sanctioned construct exists" in agents
    assert "static/local replacement" in agents


def test_frontend_skeleton_present() -> None:
    # A runnable full-stack repo ships a Vite React app whose whole wiring is renderTerpApp
    # discovering the module slots — no per-module registration.
    frontend = _PROJECT / "frontend"
    for artifact in ("package.json.jinja", "index.html.jinja", "tsconfig.json", "vite.config.ts"):
        assert (frontend / artifact).exists()
    main = (frontend / "src" / "main.tsx.jinja").read_text()
    assert "renderTerpApp(" in main
    assert 'import.meta.glob("./modules/*/module.tsx"' in main
    # `vite/client`, because react-core's own source reads `import.meta.env.DEV` — the build
    # flag that decides whether the preview bridge exists at all (ADR 0101 §1). react-core
    # compiles with `types: []` and declares that shape for itself, and its ambient file is not
    # part of a consumer's program, so an app whose tsconfig omits this fails to typecheck on a
    # line in a dependency it never wrote. Found exactly that way: apps/workbench had diverged
    # from this file and from the example, and was the only frontend in the repo that broke.
    tsconfig = json.loads((frontend / "tsconfig.json").read_text(encoding="utf-8"))
    assert "vite/client" in tsconfig["compilerOptions"]["types"], (
        "a scaffolded app compiles react-core's source, which reads import.meta.env"
    )


def test_frontend_ships_a_favicon_that_index_html_actually_links() -> None:
    # Both halves, because either one alone is silently useless: a file nothing references is
    # never fetched, and a link to a missing file leaves the tab on the browser default with
    # no error anywhere. A single-page app makes that worse than a 404 — the unrouted request
    # for /favicon.ico returns index.html, so the browser gets HTML where it asked for an icon
    # and simply gives up.
    frontend = _PROJECT / "frontend"
    favicon = frontend / "public" / "favicon.svg"
    assert favicon.exists(), "the template ships no default tab mark"
    index = (frontend / "index.html.jinja").read_text(encoding="utf-8")
    assert 'href="/favicon.svg"' in index
    assert 'rel="icon"' in index
    # And it carries both appearances itself. A favicon is a separate document that never sees
    # the page's tokens, so this is the only place its dark variant can live.
    assert "prefers-color-scheme: dark" in favicon.read_text(encoding="utf-8")


def test_frontend_templates_have_no_unescaped_jsx_double_braces() -> None:
    # In a copier .jinja file `{{ ... }}` is a Jinja expression, so a JSX inline-style
    # object (`style={{ ... }}`) would be mis-parsed. The frontend starter must avoid it.
    home = _PROJECT / "frontend" / "src" / "modules" / "home"
    for tsx in ("module.tsx.jinja", "Home.tsx.jinja"):
        assert "style={{" not in (home / tsx).read_text()


def test_frontend_ships_escape_hatch_budget() -> None:
    # The governed boundary opt-out: the checked-in budget starts empty, and the lint
    # command runs the ratchet in the same invocation as the boundary rules (a failing
    # lint can never skip it — a `terp-allow-*` marker count must match it exactly).
    assert (_PROJECT / "frontend" / "escape-hatch-budget.json").read_text().strip() == "{}"
    package = (_PROJECT / "frontend" / "package.json.jinja").read_text()
    assert "terp-boundaries-lint" in package


def test_project_ships_frontend_ci() -> None:
    # The generated repo is full-stack, so its CI has to be able to run the frontend half
    # of the gate: the boundary lint, the typecheck and the build all live in the `full`
    # profile, and all of them shell out to npm. What CI owes them is node and an
    # installed frontend/node_modules — naming the checks is the profile's job
    # (test_cli_verify.py::test_the_full_profile_is_the_template_ci_surface).
    ci = (_PROJECT / ".github" / "workflows" / "ci.yml.jinja").read_text()
    assert "actions/setup-node" in ci
    assert "npm --prefix frontend install" in ci
    assert "terp verify --profile full" in ci


def test_frontend_ships_typed_client_codegen() -> None:
    # A generated repo types calls to its OWN endpoints: openapi-typescript turns the app's
    # OpenAPI into a `paths` type, passed to useTerpClient<paths>(). The generated schema is
    # a build artifact, so it is git-ignored.
    package = (_PROJECT / "frontend" / "package.json.jinja").read_text()
    assert "openapi-typescript" in package
    assert '"generate"' in package
    # The routes half of the codegen pair (ADR 0092): the script that extracts the
    # module manifests, plus the committed table a fresh app's gate checks against —
    # without the checked-in file the generated app's own CI would fail on step one.
    assert '"routes": "terp-routes"' in package
    committed_table = _PROJECT / "frontend" / "src" / "routes.gen.d.ts.jinja"
    assert committed_table.is_file(), "a generated app must ship its route table committed"
    table = committed_table.read_text(encoding="utf-8")
    assert 'declare module "@terpjs/react-core"' in table
    assert '"/": Record<never, never>;' in table, "the home module's route must be keyed"
    assert "frontend/src/api/" in (_PROJECT / ".gitignore").read_text()


def test_project_ci_generates_the_typed_client_before_type_checking() -> None:
    """CI must produce the client it git-ignores, or the frontend gate is theatre.

    The two rules above are individually right and jointly a trap: the typed client is a
    build artifact (git-ignored), so a fresh checkout does not have one. Vite erases
    type-only imports, so `npm run build` passes regardless and only `tsc` fails — which
    means the omission is invisible on the blank scaffold and becomes a permanent CI
    failure the moment a module first imports the client. Generating it is what makes
    the frontend half of the gate a check rather than a formality.

    Wiring that into CI as a pair of steps was right and still not enough: the workflow
    is SCAFFOLDED, so a fielded app's copy freezes at the version it was rendered from.
    An app that never re-renders keeps a `frontend` job with no codegen in it, and the
    trap springs exactly as described above — against a workflow this repo believes it
    fixed. So generating the client is now the profile's `api-client` check, ordered
    ahead of `frontend-typecheck` (test_cli_verify.py::
    test_every_profile_that_typechecks_the_frontend_generates_its_client), and CI only
    has to invoke the profile. Codegen steps of its own are the defect, not the fix.
    """
    ci = (_PROJECT / ".github" / "workflows" / "ci.yml.jinja").read_text()
    assert "terp verify --profile full" in ci, (
        "the client is generated by the profile's api-client check, so CI must invoke "
        "the profile rather than carry codegen steps of its own"
    )
    assert "npm run generate" not in ci, (
        "codegen as a CI step is the failure this test documents: it froze at the "
        "template version each app was rendered from and quietly stopped running"
    )


def test_project_ships_a_docker_workbench() -> None:
    # The generated repo runs the "right way": a Postgres-backed Compose workbench that seeds
    # itself and live-reloads, mirroring the (live-proven) apps/example workbench.
    assert (_PROJECT / "Dockerfile").exists()
    assert (_PROJECT / "frontend" / "Dockerfile").exists()
    assert (_PROJECT / ".dockerignore").exists()
    assert (_PROJECT / ".env.example.jinja").exists()
    compose = (_PROJECT / "docker-compose.yml.jinja").read_text()
    for service in ("db:", "migrate:", "seed:", "api:", "web:"):
        assert service in compose
    # Health-gated ordering: api waits for a healthy db and a completed migrate.
    assert "service_healthy" in compose
    assert "service_completed_successfully" in compose
    # `docker compose watch` live-sync + the same-origin API proxy target.
    assert "watch:" in compose
    assert "TERP_API_PROXY" in compose
    # ...and the vite config actually honors it: inside the web container the compose-set
    # TERP_API_PROXY must win over the localhost default (localhost:8000 inside the web
    # container is the web container itself — proxying there 502s every sign-in).
    vite_config = (_PROJECT / "frontend" / "vite.config.ts").read_text()
    assert "process.env.TERP_API_PROXY" in vite_config
    # The README teaches the one-command workbench.
    assert "terp docker dev" in (_PROJECT / "README.md.jinja").read_text()


def test_project_ships_a_seed() -> None:
    # `terp seed` runs app.seed:seed; the template provisions a first admin (so the app is
    # loginnable) plus demo rows through the audited services.
    seed = (_PROJECT / "app" / "seed.py.jinja").read_text()
    assert "def seed(session" in seed
    assert "UsersService" in seed
    assert "UserProvision" in seed
    assert "Roles.ADMIN" in seed


def test_frontend_offers_the_seeded_dev_sign_in() -> None:
    # The login screen can one-click-fill the seeded dev credentials, but only in dev
    # builds: import.meta.env.DEV is statically false in production bundles, so the
    # credentials never ship. The email must match what app/seed.py provisions.
    main = (_PROJECT / "frontend" / "src" / "main.tsx.jinja").read_text()
    assert "devCredentials" in main
    assert "import.meta.env.DEV" in main
    seed = (_PROJECT / "app" / "seed.py.jinja").read_text()
    assert 'admin@example.test' in main
    assert 'admin@example.test' in seed


def test_project_ships_a_migration_drift_gate() -> None:
    # The generated repo's own suite runs the reusable drift check (upgrade a scratch
    # database, then alembic-check every history): a model edited without
    # `terp migrate make` fails the project's CI, not production. The consumer complement
    # of the monorepo's test_migrations_conformance drift test — without it, the
    # tables_have_migrations rule (a history exists) and the boot guard (nothing pending)
    # both pass while the live schema silently diverges from the model.
    gate = (_PROJECT / "tests" / "test_architecture.py.jinja").read_text()
    assert "assert_migrations_match_models" in gate
    assert "upgrade(" in gate


def test_project_gate_refuses_unmounted_modules() -> None:
    # App modules are mounted explicitly in app/main.py — a scaffolded module that
    # never gets added to the `modules` list serves zero routes while every other
    # check stays green (seen live: an agent-built module 404'd and was absent
    # from the exported contract). The generated suite must fail closed on it.
    gate = (_PROJECT / "tests" / "test_architecture.py.jinja").read_text()
    assert "def test_every_module_is_mounted" in gate
    assert "add it to the `modules` list" in gate


def test_project_ships_frontend_boundary_lint() -> None:
    # The generated repo enforces frontend module boundaries (the analog of `terp check`): no
    # cross-module imports, no package internals, tokens-only styling, generated client only.
    assert (_PROJECT / "frontend" / "eslint.config.js").exists()
    package = (_PROJECT / "frontend" / "package.json.jinja").read_text()
    assert "@terpjs/eslint-boundaries" in package
    assert '"lint"' in package
    assert '"eslint"' in package


def test_project_ships_conformance_e2e() -> None:
    # The generated repo ships a Playwright conformance project (the base-profile auth/logout flows
    # from @terpjs/conformance) + a CI job that boots the workbench and runs it — the browser-level
    # complement to the type/build checks, ready to grow with the app's own module specs.
    conformance = _PROJECT / "conformance"
    assert (conformance / "playwright.config.ts").exists()
    assert (conformance / "tsconfig.json").exists()
    package = (conformance / "package.json.jinja").read_text()
    assert "@terpjs/conformance" in package
    assert "@playwright/test" in package
    spec = (conformance / "tests" / "auth.spec.ts").read_text()
    assert "@terpjs/conformance" in spec
    assert "logout" in spec
    # CI boots the workbench and runs the suite (the browser-level gate).
    ci = (_PROJECT / ".github" / "workflows" / "ci.yml.jinja").read_text()
    assert "playwright install" in ci
    assert "docker compose up" in ci


def test_template_route_table_matches_what_the_generator_emits() -> None:
    """The template ships a COMMITTED copy of a generated file, and a scaffolded app
    runs `terp routes --check` against it in its own CI — so a reworded generator and
    a stale template copy fail the app rather than the framework.

    That is exactly what happened: ADR 0096 added declared query-string keys and
    reworded the generator's header to name `useRouteSearch`, the template's copy kept
    the old wording, and three of the four layout presets went red in
    template-acceptance while every gate in this suite stayed green. The search table
    itself was never the problem — the generator omits it when no route declares keys,
    which is precisely so this file stays valid.

    Compared as the generator's own header literals rather than as a pasted copy, so
    the next rewording fails here, in seconds, instead of in a scaffolded app's CI.
    """
    codegen = _CODEGEN.read_text(encoding="utf-8")
    start = codegen.index("const HEADER = [")
    block = codegen[start : codegen.index("];", start)]
    literal = re.compile(r"""^\s*("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'),?\s*$""", re.M)
    header = [
        match.group(1)[1:-1].replace('\\"', '"').replace("\\'", "'")
        for match in literal.finditer(block)
    ]
    assert header, "could not read HEADER out of routes-codegen.js"
    assert header[-1].strip() == "interface TerpRouteTable {", (
        f"HEADER no longer ends by opening the route table: {header[-1]!r}"
    )

    table = (
        _PROJECT / "frontend/src/routes.gen.d.ts.jinja"
    ).read_text(encoding="utf-8").splitlines()
    assert table[: len(header)] == header, (
        "template/project/frontend/src/routes.gen.d.ts.jinja is stale against "
        "routes-codegen.js — re-render its header from the generator's HEADER"
    )
    # The module-less presets declare exactly one route and no search keys, so the
    # generator emits one entry and the two closes. `hub-all-capabilities` mounts more
    # and is excluded from the acceptance check for that reason.
    assert table[len(header) :] == [
        '    "/": Record<never, never>;',
        "  }",
        "}",
    ], f"unexpected route-table body: {table[len(header):]!r}"


# --------------------------------------------------------------------------- #
# The generated app's own documentation describes the app it actually is.
#
# This is the class of defect nothing else here can see. A scaffolded app carries
# prose about itself, and that prose is what an agent — or a developer who never
# installs any tool beyond this framework — reads to answer "how do I change the
# way this looks?". It rotted exactly that way: the framework grew from two
# palettes to five and three files kept saying two, while a fourth file in the
# same template said "this app ships three dark themes" four lines further down.
# --------------------------------------------------------------------------- #


def test_the_scaffolded_app_names_every_palette_it_actually_ships() -> None:
    """Both places a person looks: the entry point they open, and their AGENTS.md.

    Asserted against react-core's own THEMES rather than a list written here, so
    a sixth palette fails this instead of quietly making the docs wrong again.
    """
    palettes = _shipped_palettes()
    for name, path in (
        ("main.tsx.jinja", _PROJECT / "frontend" / "src" / "main.tsx.jinja"),
        ("AGENTS.md.jinja", _PROJECT / "AGENTS.md.jinja"),
    ):
        text = path.read_text(encoding="utf-8")
        missing = [palette for palette in palettes if palette not in text]
        assert not missing, (
            f"{name} does not name {missing}; a scaffolded app whose own docs list "
            f"fewer palettes than it ships sends its reader looking for a theme "
            f"switcher that is already there"
        )


def test_the_scaffolded_app_does_not_describe_itself_as_two_themed() -> None:
    """The specific sentences that were wrong, refused by shape.

    A positive check that every palette is NAMED does not catch a sentence that
    names them all and then says "both palettes" two lines later — the file would
    contain each name and still tell the reader there are two. So the phrasings
    that carried the claim are refused outright.
    """
    banned = (
        "both palettes",
        "both the light and dark",
        "light and dark palettes",
        "Dark/light theme",
        "(light / dark / system)",
        "(light/dark/system)",
    )
    for path in sorted(_PROJECT.rglob("*")):
        if not path.is_file() or path.suffix not in {".jinja", ".css", ".md", ".tsx", ".ts"}:
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        for phrase in banned:
            assert phrase not in content, (
                f"{path.relative_to(_PROJECT)} says {phrase!r}; this framework ships "
                f"{len(_shipped_palettes())} palettes"
            )


def test_the_scaffolded_app_puts_the_theme_toggle_where_it_actually_is() -> None:
    """The docs said the user menu; the component tree says the shell header.

    Pinned to the component tree, not to itself. An agent asked to "move the theme
    switch" reads AGENTS.md, goes to UserMenu, finds nothing, and starts guessing —
    and the same sentence credited that menu with the language switch, which is
    also elsewhere. If the toggle is ever genuinely moved into the user menu, this
    fails and the prose gets revisited with it.
    """
    shell = (_REACT_CORE / "AppShell.tsx").read_text(encoding="utf-8")
    menu = (_REACT_CORE / "UserMenu.tsx").read_text(encoding="utf-8")
    assert "<ThemeToggle" in shell, "the shell no longer renders the theme toggle"
    assert "<ThemeToggle" not in menu, (
        "the theme toggle moved into the user menu — the template's AGENTS.md says "
        "it is in the shell header, and now needs revisiting"
    )
    assert "<LanguageSwitcher" in shell and "<LanguageSwitcher" not in menu

    agents = (_PROJECT / "AGENTS.md.jinja").read_text(encoding="utf-8")
    assert "shell header" in agents, (
        "the generated AGENTS.md no longer tells its reader where the theme toggle is"
    )


def test_the_scaffolded_theme_overlay_belongs_to_the_app() -> None:
    """`theme.css` is the app's styling seam, and must read as one.

    It shipped titled "Studio-managed theme overlay" and explained itself entirely
    in terms of a product the developer may never install — so the one file that
    answers "where do I change the colours?" answered "somewhere else". A tool
    that generates it is a fact worth stating, and it is stated; it is not the
    file's identity.
    """
    overlay = (_PROJECT / "frontend" / "src" / "theme.css").read_text(encoding="utf-8")
    first_line = overlay.splitlines()[0]
    assert "Studio" not in first_line, (
        f"theme.css introduces itself as {first_line!r} — a developer with no such "
        f"tool must still read this as their own file"
    )
    assert "terp guide theming" in overlay, (
        "theme.css should point at the recipe that is always available"
    )


def _document_location_block(config: str) -> str:
    """The ``location /`` block that serves index.html (the SPA fallback).

    Sliced textually because the assertion below is specifically about *where* in
    the file the headers sit: nginx applies ``add_header`` from an outer level only
    when the block declares none of its own, so a header on the ``server`` block is
    not a header on this response.
    """
    start = config.index("location / {")
    return config[start : config.index("}", start)]


def test_frontend_serves_document_security_headers() -> None:
    # The SPA document, not the API, is where these decide anything: a CSP on a JSON
    # response governs subresources a JSON body never loads and framing it cannot
    # suffer, while the header on the HTML document decides whether a third-party
    # script may execute, whether the app may be framed, and where it may connect.
    # nginx serves that document, and shipped no security headers on it at all.
    #
    # Asserted *inside* the document location on purpose. Hoisting these to the
    # server block is the obvious DRY refactor and it silently breaks the control —
    # measured against a real nginx, the document then carries Cache-Control alone,
    # because both content locations declare add_header of their own and nginx drops
    # every inherited one. This test is what stops that refactor landing.
    for config in (
        _PROJECT / "frontend" / "nginx.conf",
        pathlib.Path(__file__).resolve().parents[2] / "apps/example/frontend/nginx.conf",
    ):
        document = _document_location_block(config.read_text(encoding="utf-8"))
        for header, expected in (
            ("Content-Security-Policy", "frame-ancestors 'none'"),
            ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "no-referrer"),
            ("Cross-Origin-Opener-Policy", "same-origin"),
        ):
            assert header in document, f"{config.name}: no {header} on the document"
            assert expected in document, f"{config.name}: {header} lost {expected!r}"
        # No 'unsafe-inline' anywhere. react-core delivers its token stylesheet
        # through adoptedStyleSheets, which CSP does not govern, so nothing on the
        # page needs the keyword — and it cannot be reintroduced for styles without
        # also permitting any other inline stylesheet an injection may add.
        csp = document[document.index("Content-Security-Policy") :]
        csp = csp[: csp.index("always;")]
        assert "script-src 'self';" in csp, f"{config.name}: script-src is not exactly 'self'"
        assert "style-src 'self';" in csp, f"{config.name}: style-src is not exactly 'self'"
        assert "'unsafe-inline'" not in csp, (
            f"{config.name}: 'unsafe-inline' is back in the policy — react-core's "
            "adopted stylesheet means no part of the page requires it"
        )


def test_dev_server_holds_the_same_origin_rules_as_production() -> None:
    # Production serves a strict policy; a dev server with none means a
    # CSP-incompatible pattern — an agent reaching for a CDN chart library is the
    # motivating case — works all the way to deploy before anything objects. The
    # dev policy therefore keeps production's *origin* rules exactly, and relaxes
    # only what Vite's own machinery forces: the Fast Refresh preamble is an
    # inline script and imported CSS arrives as an injected <style>.
    #
    # Measured against a running dev server rather than assumed: a CDN script, an
    # external stylesheet and a cross-origin fetch are each refused, and HMR still
    # reports "[vite] connected." under `connect-src 'self'` with no `ws:`.
    for config in (
        _PROJECT / "frontend" / "vite.config.ts",
        pathlib.Path(__file__).resolve().parents[2] / "apps/example/frontend/vite.config.ts",
    ):
        source = config.read_text(encoding="utf-8")
        assert "Content-Security-Policy" in source, f"{config}: dev server sets no policy"
        policy = source[source.index("devContentSecurityPolicy = [") :]
        policy = policy[: policy.index("].join")]

        for directive in (
            '"default-src \'self\'"',
            '"connect-src \'self\'"',
            '"object-src \'none\'"',
            '"frame-ancestors \'none\'"',
        ):
            assert directive in policy, f"{config}: dev policy is missing {directive}"

        # `connect-src` must not widen to a scheme: 'self' already covers the HMR
        # socket, and `ws:` would allow a socket to any host.
        assert "ws:" not in policy, f"{config}: connect-src widened to ws: — 'self' suffices"

        # No third-party origin, and no wildcard, anywhere in the dev policy: the
        # whole point is that dev refuses what production refuses.
        assert "http://" not in policy and "https://" not in policy, (
            f"{config}: a third-party origin is allowed in dev but not in production"
        )
        assert "*" not in policy, f"{config}: a wildcard origin defeats the parity"

        # The two dev-only relaxations, and *only* those two.
        relaxed = [
            line.split('"')[1]
            for line in policy.splitlines()
            if "'unsafe-inline'" in line and line.strip().startswith('"')
        ]
        assert sorted(relaxed) == [
            "script-src 'self' 'unsafe-inline'",
            "style-src 'self' 'unsafe-inline'",
        ], f"{config}: 'unsafe-inline' reaches directives beyond script/style: {relaxed}"
        assert "'unsafe-eval'" not in policy, f"{config}: 'unsafe-eval' is never needed here"
