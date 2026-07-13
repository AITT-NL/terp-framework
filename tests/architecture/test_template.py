"""Template skeleton integrity — the copier client-app template scaffolds a real app.

Validates the structure deterministically (no copier install required): the five module
slots, the composition root, the control plane, the discovered base profile, and the
generated `AGENTS.md`. The five-slot *shape* is exercised by test_cli_scaffold.py, which
asserts the equivalent `terp new module` output passes every architecture rule.
"""

from __future__ import annotations

import pathlib
import re

_TEMPLATE = pathlib.Path(__file__).resolve().parents[2] / "template"
_PROJECT = _TEMPLATE / "project"


def test_copier_config_declares_inputs_and_subdirectory() -> None:
    config = (_TEMPLATE / "copier.yml").read_text()
    assert "_subdirectory: project" in config
    for var in ("project_name", "project_slug", "module_name", "layout"):
        assert var in config


def test_copier_declares_the_layout_presets_and_capability_toggles() -> None:
    # The create wizard's deterministic surface: three layout presets and the
    # capability toggles whose wiring the template renders end-to-end. Every
    # toggle here must stay provably green in the template-acceptance matrix.
    config = (_TEMPLATE / "copier.yml").read_text()
    for choice in ("list", "hub", "blank"):
        assert f": {choice}" in config
    for toggle in ("use_files", "use_sso", "use_events"):
        assert toggle in config
    # The blank layout renders module_name empty, which makes copier skip the
    # starter-module trees entirely (an empty rendered path segment is skipped).
    assert "{% if layout == 'blank' %}{% else %}records{% endif %}" in config
    assert "when: \"{{ layout != 'blank' }}\"" in config
    # ...and the derived PascalCase name must tolerate that empty value.
    assert "{% if module_name %}" in config


def test_runnable_app_skeleton_present() -> None:
    main = (_PROJECT / "app" / "main.py.jinja").read_text()
    assert "create_app(" in main
    assert (_PROJECT / "control_plane" / "__init__.py").exists()
    assert (_PROJECT / "pyproject.toml.jinja").exists()
    assert (_PROJECT / "AGENTS.md.jinja").exists()


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
    # The generated repo claims `terp check` == CI, so a CI workflow must ship; and the
    # hatchling build backend needs an explicit `app` package to build.
    ci = (_PROJECT / ".github" / "workflows" / "ci.yml.jinja").read_text()
    assert "uv run pytest" in ci
    # CI regenerates the API reference and fails on drift, so a committed docs/ contract
    # cannot silently fall behind the installed kernel (the api-docs drift gate).
    assert "terp api-docs" in ci
    assert "git diff --exit-code" in ci
    pyproject = (_PROJECT / "pyproject.toml.jinja").read_text()
    assert 'packages = ["app", "control_plane"]' in pyproject


def test_example_module_has_five_slots() -> None:
    module = _PROJECT / "app" / "modules" / "{{ module_name }}"
    for slot in ("models", "schemas", "service", "router", "module"):
        assert (module / f"{slot}.py.jinja").exists()
    assert "BaseTable" in (module / "models.py.jinja").read_text()


def test_copier_declares_derived_module_pascal() -> None:
    # The React view/nav identifiers are PascalCase; a derived (non-prompted) copier
    # variable computes them from module_name so a template module and a `terp new module`
    # module look identical (mirrors the CLI scaffolder's _pascal).
    config = (_TEMPLATE / "copier.yml").read_text()
    assert "module_pascal" in config
    assert "{{ module_name[0] | upper }}{{ module_name[1:] }}" in config
    assert "when: false" in config


def test_layout_presets_render_a_home_module() -> None:
    # Hub and blank layouts get a frontend-only `home` module owning "/" (the dir name is a
    # copier conditional: it renders empty — and is skipped — for the single-list layout).
    home = _PROJECT / "frontend" / "src" / "modules" / "{% if layout != 'list' %}home{% endif %}"
    manifest = (home / "module.tsx.jinja").read_text()
    assert "defineModuleManifest(" in manifest
    assert 'path: "/"' in manifest
    view = (home / "Home.tsx.jinja").read_text()
    # Hub: a HubPage of cards, linking through the stack's router Link (no raw anchors).
    assert "HubPage" in view
    assert "HubCard" in view
    assert 'import { Link } from "@tanstack/react-router"' in view
    assert "renderLink=" in view
    # Blank: a plain archetype-framed welcome page pointing at `terp new module`.
    assert "Page" in view
    assert "terp new module" in view
    assert "style={{" not in view
    # The starter module vacates "/" for the hub layout and keeps it otherwise.
    records = (
        _PROJECT / "frontend" / "src" / "modules" / "{{ module_name }}" / "module.tsx.jinja"
    ).read_text()
    assert "{% if layout == 'hub' %}/{{ module_name }}{% else %}/{% endif %}" in records


def test_capability_toggles_wire_the_composition_root() -> None:
    # A toggled capability is a dependency AND its composition-root wiring — never a
    # half-mounted dep. Files rides discovery; SSO/events need explicit seams.
    pyproject = (_PROJECT / "pyproject.toml.jinja").read_text()
    for dep in ("terp-cap-files", "terp-cap-oidc", "terp-cap-eventbus"):
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
    assert 'ssoProviders: [{ name: "sso", label: "Single sign-on" }]' in main_tsx
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
        r"(?<!uv run )\bterp (?:guide|check|dev|new|inspect|migrate|openapi|docker|user)\b"
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


def test_frontend_skeleton_present() -> None:
    # A runnable full-stack repo ships a Vite React app whose whole wiring is renderTerpApp
    # discovering the module slots — no per-module registration.
    frontend = _PROJECT / "frontend"
    for artifact in ("package.json.jinja", "index.html.jinja", "tsconfig.json", "vite.config.ts"):
        assert (frontend / artifact).exists()
    main = (frontend / "src" / "main.tsx.jinja").read_text()
    assert "renderTerpApp(" in main
    assert 'import.meta.glob("./modules/*/module.tsx"' in main


def test_frontend_example_module_slot_present() -> None:
    module = _PROJECT / "frontend" / "src" / "modules" / "{{ module_name }}"
    manifest = (module / "module.tsx.jinja").read_text()
    assert "defineModuleManifest(" in manifest
    assert "export const views" in manifest
    # The starter view is named for the PascalCase module (auto-discovered by the glob).
    assert (module / "{{ module_pascal }}List.tsx.jinja").exists()
    # It composes the centralized ResourceList primitive (the same pattern the example dogfoods),
    # so a generated module lists + creates the same way as every other module.
    view = (module / "{{ module_pascal }}List.tsx.jinja").read_text()
    assert "ResourceList" in view
    assert "emptyMessage" in view
    assert "/api/v1/{{ module_name }}/" in view
    # ...framed by a page archetype (buildAppRouter refuses a routed view without one).
    assert "OverviewPage" in view


def test_frontend_ships_escape_hatch_budget() -> None:
    # The governed boundary opt-out: the checked-in budget starts empty, and the lint
    # command runs the ratchet in the same invocation as the boundary rules (a failing
    # lint can never skip it — a `terp-allow-*` marker count must match it exactly).
    assert (_PROJECT / "frontend" / "escape-hatch-budget.json").read_text().strip() == "{}"
    package = (_PROJECT / "frontend" / "package.json.jinja").read_text()
    assert "terp-boundaries-lint" in package


def test_frontend_templates_have_no_unescaped_jsx_double_braces() -> None:
    # In a copier .jinja file `{{ ... }}` is a Jinja expression, so a JSX inline-style
    # object (`style={{ ... }}`) would be mis-parsed. The frontend starter must avoid it.
    module = _PROJECT / "frontend" / "src" / "modules" / "{{ module_name }}"
    for tsx in ("module.tsx.jinja", "{{ module_pascal }}List.tsx.jinja"):
        assert "style={{" not in (module / tsx).read_text()


def test_project_ships_frontend_ci() -> None:
    # The generated repo is full-stack, so CI type-checks, lints (the boundary rules +
    # escape-hatch budget) and builds the frontend too.
    ci = (_PROJECT / ".github" / "workflows" / "ci.yml.jinja").read_text()
    assert "npm run typecheck" in ci
    assert "npm run lint" in ci
    assert "npm run build" in ci


def test_frontend_ships_typed_client_codegen() -> None:
    # A generated repo types calls to its OWN endpoints: openapi-typescript turns the app's
    # OpenAPI into a `paths` type, passed to useTerpClient<paths>(). The generated schema is
    # a build artifact, so it is git-ignored.
    package = (_PROJECT / "frontend" / "package.json.jinja").read_text()
    assert "openapi-typescript" in package
    assert '"generate"' in package
    assert "frontend/src/api/" in (_PROJECT / ".gitignore").read_text()
    view = (
        _PROJECT / "frontend" / "src" / "modules" / "{{ module_name }}" / "{{ module_pascal }}List.tsx.jinja"
    ).read_text()
    assert "useTerpClient<paths>()" in view
    assert "npm --prefix frontend run generate" in view


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
    assert "@terp/eslint-boundaries" in package
    assert '"lint"' in package
    assert '"eslint"' in package


def test_project_ships_conformance_e2e() -> None:
    # The generated repo ships a Playwright conformance project (the base-profile auth/logout flows
    # from @terp/conformance) + a CI job that boots the workbench and runs it — the browser-level
    # complement to the type/build checks, ready to grow with the app's own module specs.
    conformance = _PROJECT / "conformance"
    assert (conformance / "playwright.config.ts").exists()
    assert (conformance / "tsconfig.json").exists()
    package = (conformance / "package.json.jinja").read_text()
    assert "@terp/conformance" in package
    assert "@playwright/test" in package
    spec = (conformance / "tests" / "auth.spec.ts").read_text()
    assert "@terp/conformance" in spec
    assert "logout" in spec
    # CI boots the workbench and runs the suite (the browser-level gate).
    ci = (_PROJECT / ".github" / "workflows" / "ci.yml.jinja").read_text()
    assert "playwright install" in ci
    assert "docker compose up" in ci
