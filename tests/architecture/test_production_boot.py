"""Template acceptance boots every render in production mode: ``tools/production_boot.py``.

A deploy runs the app with ``ENVIRONMENT=production``, where the platform refuses what the
development loop only warns about, and nothing in template acceptance ran a render that way:
the template's single sign-on wiring built ``FederatedIdentityService(allow_provisioning=True)``
with no allowlist, which a production boot refuses at import, SSO configured or not. The
template now renders the allowlist from ``OIDC_ALLOWED_EMAIL_DOMAINS`` and provisions only
while SSO is configured, and the tool holds a render to three boots against PostgreSQL. It
runs in template acceptance, in the render's own environment; here its verdicts are held
with a runner that answers for the child interpreter, and the template and the lane are held
to what the tool assumes of them.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest
import yaml

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "tools"))

import production_boot as boot_tool  # noqa: E402

_AUTH = _REPO_ROOT / "template" / "project" / "app" / "auth.py.jinja"
_DATABASE = "postgresql+psycopg://postgres@localhost:5432/postgres"


def _answers(tmp_path: pathlib.Path, *, sso: bool) -> pathlib.Path:
    (tmp_path / boot_tool.ANSWERS).write_text(
        f"_commit: v0\nuse_files: true\nuse_sso: {'true' if sso else 'false'}\n",
        encoding="utf-8",
    )
    return tmp_path


class _Child:
    """Answers for every interpreter the tool starts, by what it runs and with what."""

    def __init__(self, *, ready: int = 200, refuse: str | None = None, migrate: int = 0):
        self.ready = ready
        self.refuse = refuse
        self.migrate = migrate
        self.calls: list[tuple[list[str], dict[str, str]]] = []

    def __call__(self, argv, **kwargs) -> subprocess.CompletedProcess[str]:
        env = kwargs["env"]
        self.calls.append((argv, env))
        if "migrate" in argv:
            return subprocess.CompletedProcess(argv, self.migrate, "", "migrate said no\n")
        configured = bool(env.get("OIDC_ISSUER"))
        listed = bool(env.get("OIDC_ALLOWED_EMAIL_DOMAINS"))
        if configured and not listed:
            message = self.refuse if self.refuse is not None else boot_tool.ALLOWLIST_REFUSAL
            return subprocess.CompletedProcess(argv, 1, "", f"ValueError: {message}\n")
        paths = ["/health/ready", *([boot_tool.SSO_ROUTE] if configured else [])]
        report = json.dumps({"ready": self.ready, "paths": paths})
        return subprocess.CompletedProcess(argv, 0, f"booting\n{report}\n", "")


# --------------------------------------------------------------------------- #
# the cases                                                                     #
# --------------------------------------------------------------------------- #
def test_a_render_without_sso_boots_once() -> None:
    assert boot_tool.cases(sso=False) == [boot_tool.Case("SSO not configured")]


def test_a_render_with_sso_boots_with_the_allowlist_and_is_refused_without_it() -> None:
    off, listed, unlisted = boot_tool.cases(sso=True, secret=lambda: "generated")
    assert off.env == {} and not off.sso_mounted and off.refused_with is None
    assert listed.sso_mounted and listed.refused_with is None
    assert listed.env["OIDC_ALLOWED_EMAIL_DOMAINS"] == "example.test,example.org"
    assert "OIDC_ALLOWED_EMAIL_DOMAINS" not in unlisted.env
    assert unlisted.refused_with == boot_tool.ALLOWLIST_REFUSAL
    for case in (listed, unlisted):
        assert case.env["OIDC_ISSUER"].startswith("https://"), "production refuses http"
        assert case.env["OIDC_CLIENT_SECRET"] == "generated", "never a value in a file"


def test_the_client_secret_is_generated_per_run() -> None:
    first, second = boot_tool.cases(sso=True)[1], boot_tool.cases(sso=True)[1]
    assert first.env["OIDC_CLIENT_SECRET"] != second.env["OIDC_CLIENT_SECRET"]


def test_the_refusal_it_waits_for_is_the_federated_service_s_own() -> None:
    from terp.capabilities.identity import FederatedIdentityService

    (problem,) = FederatedIdentityService(allow_provisioning=True).production_problems()
    assert boot_tool.ALLOWLIST_REFUSAL in problem


def test_the_route_it_looks_for_is_the_one_the_sso_module_mounts() -> None:
    from terp.capabilities.oidc import OIDCProviderConfig, build_oidc_module

    module = build_oidc_module(
        [
            OIDCProviderConfig(
                name="sso",
                issuer="https://idp.example.test",
                client_id="client",
                client_secret="generated",
                redirect_uri="https://app.example.test/auth/sso/callback",
            )
        ],
        lambda session, claims: None,
    )
    paths = {f"/api/v1/{module.name}{route.path}" for route in module.router.routes}
    assert boot_tool.SSO_ROUTE in paths


def test_a_case_boots_in_production_with_a_generated_key_and_nothing_inherited() -> None:
    base = {
        "PATH": "/bin",
        "ENVIRONMENT": "local",
        "SECRET_KEY": "inherited",
        "OIDC_ISSUER": "https://inherited.example.test",
        "DATABASE_URL": "sqlite://",
    }
    case = boot_tool.cases(sso=True)[1]
    env = boot_tool.production_env(_DATABASE, case, base)
    assert env["PATH"] == "/bin"
    assert env["ENVIRONMENT"] == "production"
    assert env["DATABASE_URL"] == _DATABASE
    assert env["OIDC_ISSUER"] == "https://idp.example.test"
    assert len(env["SECRET_KEY"]) == 64 and env["SECRET_KEY"] != "inherited"
    off = boot_tool.production_env(_DATABASE, boot_tool.cases(sso=False)[0], base)
    assert not any(key.startswith("OIDC_") for key in off), "SSO off means no OIDC_* at all"


# --------------------------------------------------------------------------- #
# the verdicts                                                                  #
# --------------------------------------------------------------------------- #
def test_every_case_holds_and_the_database_is_migrated_first(tmp_path, capsys) -> None:
    child = _Child()
    root = _answers(tmp_path, sso=True)
    assert boot_tool.main(["--database-url", _DATABASE, "--root", str(root)], run=child) == 0
    assert capsys.readouterr().out.splitlines() == [
        "ok  SSO not configured: boots in production, ready",
        "ok  SSO configured with OIDC_ALLOWED_EMAIL_DOMAINS: boots in production, ready, "
        "SSO mounted",
        "ok  SSO configured without an allowlist: refused in production, by name",
    ]
    (migrate, migrate_env), *boots = child.calls
    assert migrate[-4:] == ["migrate", "upgrade", "--app-root", str(root.resolve() / "app")]
    assert migrate_env["ENVIRONMENT"] == "production", "as the profile's one-shot runs it"
    assert all(argv[-1] == boot_tool.PROBE for argv, _env in boots)
    assert all(env["DATABASE_URL"] == _DATABASE for _argv, env in child.calls)


def test_a_render_without_sso_is_booted_once(tmp_path, capsys) -> None:
    child = _Child()
    root = _answers(tmp_path, sso=False)
    assert boot_tool.main(["--database-url", _DATABASE, "--root", str(root)], run=child) == 0
    assert capsys.readouterr().out == "ok  SSO not configured: boots in production, ready\n"
    assert len(child.calls) == 2


def test_a_tree_that_is_not_a_render_is_refused(tmp_path, capsys) -> None:
    assert boot_tool.main(["--database-url", _DATABASE, "--root", str(tmp_path)]) == 1
    assert "no .copier-answers.yml in" in capsys.readouterr().err


def test_a_failed_migration_stops_the_boot(tmp_path, capsys) -> None:
    child = _Child(migrate=1)
    root = _answers(tmp_path, sso=False)
    assert boot_tool.main(["--database-url", _DATABASE, "--root", str(root)], run=child) == 1
    assert capsys.readouterr().err == (
        "production_boot: terp migrate upgrade exited 1:\nmigrate said no\n\n"
    )


def _boot(case: boot_tool.Case, child: _Child) -> str:
    return boot_tool.boot(pathlib.Path("."), _DATABASE, case, child, sys.executable)


def test_a_boot_that_fails_says_so_with_its_output() -> None:
    def crash(argv, **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 1, "", "BootError: a refusal\n")

    with pytest.raises(
        boot_tool.BootError, match="SSO not configured: the production boot failed:\nBootError"
    ):
        boot_tool.boot(pathlib.Path("."), _DATABASE, boot_tool.cases(sso=False)[0], crash, "py")


def test_a_boot_that_is_not_ready_is_refused() -> None:
    with pytest.raises(boot_tool.BootError, match="answered 503, not 200"):
        _boot(boot_tool.cases(sso=False)[0], _Child(ready=503))


def test_sso_routes_must_be_mounted_exactly_where_sso_is_configured() -> None:
    off, listed, _unlisted = boot_tool.cases(sso=True)
    with pytest.raises(boot_tool.BootError, match="the SSO routes are mounted"):
        _boot(boot_tool.Case(off.name, listed.env), _Child())
    with pytest.raises(boot_tool.BootError, match="the SSO routes are not mounted"):
        _boot(boot_tool.Case(listed.name, {}, sso_mounted=True), _Child())


def test_a_case_that_must_be_refused_and_boots_is_a_failure() -> None:
    _off, listed, unlisted = boot_tool.cases(sso=True)
    with pytest.raises(boot_tool.BootError, match="booted in production, where it must be"):
        _boot(boot_tool.Case(unlisted.name, listed.env, refused_with="anything"), _Child())


def test_a_refusal_for_another_reason_is_a_failure() -> None:
    unlisted = boot_tool.cases(sso=True)[2]
    with pytest.raises(boot_tool.BootError, match="refused, but not with"):
        _boot(unlisted, _Child(refuse="SECRET_KEY must be a strong value"))


# --------------------------------------------------------------------------- #
# what the tool assumes of the template and the lane                            #
# --------------------------------------------------------------------------- #
def test_the_template_renders_the_allowlist_and_provisions_only_with_sso() -> None:
    """The template half: the allowlist comes from OIDC_ALLOWED_EMAIL_DOMAINS, and JIT
    provisioning is on only while an issuer is configured, so a render with SSO off is not
    refused for an allowlist it has no use for."""
    source = _AUTH.read_text(encoding="utf-8")
    sso = source.split("{% if use_sso %}", 1)[1]
    assert 'os.environ.get("OIDC_ALLOWED_EMAIL_DOMAINS", "")' in sso
    assert "allow_provisioning=bool(_OIDC_ISSUER)," in sso
    assert "allowed_email_domains=_ALLOWED_EMAIL_DOMAINS or None," in sso
    assert "FederatedIdentityService(allow_provisioning=True)" not in source
    for path in ("docker-compose.yml.jinja", ".env.example.jinja"):
        text = (_REPO_ROOT / "template" / "project" / path).read_text(encoding="utf-8")
        assert "OIDC_ALLOWED_EMAIL_DOMAINS" in text.split("if use_sso", 1)[1], path


def _acceptance() -> dict:
    workflow = yaml.safe_load(
        (_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    return workflow["jobs"]["template-acceptance"]


def test_template_acceptance_boots_every_render_against_postgresql() -> None:
    job = _acceptance()
    postgres = job["services"]["postgres"]
    assert postgres["image"].startswith("postgres:17")
    assert postgres["env"] == {"POSTGRES_HOST_AUTH_METHOD": "trust"}, "no password in a file"
    (step,) = [s for s in job["steps"] if "tools/production_boot.py" in str(s.get("run", ""))]
    assert step["if"] == "${{ !startsWith(matrix.variant, 'reference') }}"
    assert step["working-directory"] == "/tmp/acceptance-app"  # noqa: S108 - the CI runner's path
    assert "job.services.postgres.ports['5432']" in step["env"]["BOOT_DATABASE_URL"]
    assert step["run"].startswith("uv run python "), "in the render's own environment"
    variants = {e["variant"]: e["copier-args"] for e in job["strategy"]["matrix"]["include"]}
    assert "use_sso=true" in variants["hub-all-capabilities"], "one render boots with SSO"


def test_template_acceptance_runs_the_production_profile_with_files_and_sso_on_docker() -> None:
    (step,) = [
        s for s in _acceptance()["steps"]
        if "The production profile on Docker" in s.get("name", "")
    ]
    assert step["if"] == "matrix.variant == 'hub-all-capabilities'"
    include = _acceptance()["strategy"]["matrix"]["include"]
    assert "use_files=true" in {e["variant"]: e["copier-args"] for e in include}[
        "hub-all-capabilities"
    ]
    run = step["run"]
    for fragment in (
        "UV_FIND_LINKS=.terp-dist/wheels uv lock",
        "OIDC_ALLOWED_EMAIL_DOMAINS=example.test",
        "$profile up -d --wait api",
        'assert os.path.ismount(root)',
        "assert root.stat().st_uid == os.getuid()",
        '$profile run --rm --no-deps api python -c',
        "my-terp-app-prod_files-data",
        "$profile down -v",
        # The profile's images are `:?`-tagged per release (ADR 0185), so every compose
        # command on it needs the tag set.
        "export SECRET_KEY POSTGRES_PASSWORD TERP_RELEASE_TAG",
    ):
        assert fragment in run, fragment
    assert "SECRET_KEY=\"$(secret)\"" in run and "POSTGRES_PASSWORD=\"$(secret)\"" in run
