"""``terp verify --only env-seams`` — which seam actually supplies a declared variable.

Compose resolves a service's ``environment:`` mapping over its ``env_file:`` list, so a
variable named in both is supplied by the developer's ``.env`` and the ``.app.env`` Studio
renders never arrives. Nothing fails at that moment: the value is simply wrong, in every
environment, until something uses it — which is why this is a gate and not a warning.

Docker is not required and never will be: the verdict is a read of two checked-in files
(``environment.schema.json`` and the compose profiles). ``docker compose config`` is not
used deliberately — it inlines ``env_file`` into ``environment`` and drops the key, which
erases the exact distinction under test.
"""

from __future__ import annotations

import json
import pathlib
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.cli.envseams import (  # noqa: E402
    _is_loopback,
    env_seam_findings,
    run_env_seams_check,
)

_COMPOSE = """\
name: app
x-backend: &backend
  image: app-backend
  env_file:
    - path: .app.env
      required: false
  environment: &backend-env
{environment}
services:
  db:
    image: postgres:17-alpine
    environment:
      POSTGRES_USER: app
  migrate:
    <<: *backend
    command: ["terp", "migrate", "upgrade"]
  api:
    <<: *backend
    environment:
      <<: *backend-env
      WATCHFILES_FORCE_POLLING: "true"
"""


def _project(
    tmp_path: pathlib.Path,
    *,
    declared: dict,
    environment: str = "    ENVIRONMENT: local",
) -> pathlib.Path:
    (tmp_path / "environment.schema.json").write_text(
        json.dumps({"type": "object", "properties": declared, "required": []}),
        encoding="utf-8",
    )
    (tmp_path / "docker-compose.yml").write_text(
        _COMPOSE.format(environment=environment), encoding="utf-8"
    )
    return tmp_path


# --------------------------------------------------------------------------- #
# the shadowing verdict
# --------------------------------------------------------------------------- #
def test_a_declared_variable_forwarded_through_interpolation_is_refused(
    tmp_path: pathlib.Path,
) -> None:
    root = _project(
        tmp_path,
        declared={"MY_VAR": {"type": "string"}},
        environment="    MY_VAR: ${MY_VAR:-}",
    )
    exit_code, output = run_env_seams_check(root)
    assert exit_code == 1
    assert "MY_VAR" in output
    # The message must name the seam that wins, not merely that something is wrong.
    assert "environment:" in output and "env_file:" in output
    assert ".app.env" in output


def test_a_declared_variable_hardcoded_in_compose_is_refused(
    tmp_path: pathlib.Path,
) -> None:
    """A literal discards `.app.env` as completely as a `${}` forward.

    Scanning only for interpolation would miss the shape apps reach for most — the
    reporting app's own `FAST_SYNC_API_BASE_URL: http://api:8000`.
    """
    root = _project(
        tmp_path,
        declared={"MY_VAR": {"type": "string"}},
        environment="    MY_VAR: http://api:8000",
    )
    exit_code, output = run_env_seams_check(root)
    assert exit_code == 1
    assert "hardcoded" in output


def test_one_offence_per_variable_not_one_per_service(tmp_path: pathlib.Path) -> None:
    """A shared backend anchor puts the override on every service that merges it.

    Reporting it once per service would restate one fact N times with the fix recipe
    repeated each time — the noise that buries the finding.
    """
    root = _project(
        tmp_path,
        declared={"MY_VAR": {"type": "string"}},
        environment="    MY_VAR: ${MY_VAR:-}",
    )
    findings = env_seam_findings(root)
    assert len(findings) == 1
    assert set(findings[0].services) == {"api", "migrate"}


def test_an_undeclared_forward_is_allowed(tmp_path: pathlib.Path) -> None:
    """`.env` stays the developer's override knob — do not over-correct.

    OIDC_REDIRECT_URI is the canonical case: the browser resolves it, so a host address
    is right and a `${}` forward is the correct seam. Only a *declared* name is refused.
    """
    root = _project(
        tmp_path,
        declared={"MY_VAR": {"type": "string"}},
        environment="    OIDC_REDIRECT_URI: ${OIDC_REDIRECT_URI:-}",
    )
    assert run_env_seams_check(root)[0] == 0


def test_a_service_that_does_not_forward_app_env_is_not_a_shadow(
    tmp_path: pathlib.Path,
) -> None:
    """Without the `.app.env` seam there is nothing to shadow (the `db` service)."""
    root = _project(tmp_path, declared={"POSTGRES_USER": {"type": "string"}})
    assert run_env_seams_check(root)[0] == 0


# --------------------------------------------------------------------------- #
# the host / container / browser verdict
# --------------------------------------------------------------------------- #
def test_a_container_resolved_variable_set_to_loopback_is_refused(
    tmp_path: pathlib.Path,
) -> None:
    root = _project(
        tmp_path, declared={"API_URL": {"type": "string", "resolvedBy": "container"}}
    )
    (root / ".app.env").write_text("API_URL=http://127.0.0.1:8000\n", encoding="utf-8")
    exit_code, output = run_env_seams_check(root)
    assert exit_code == 1
    assert "loopback" in output
    assert "container itself" in output


def test_a_host_resolved_variable_may_be_loopback(tmp_path: pathlib.Path) -> None:
    """The distinction is the point: a host address is correct for a host-resolved
    variable, and flagging it would make the annotation useless."""
    root = _project(
        tmp_path, declared={"API_URL": {"type": "string", "resolvedBy": "host"}}
    )
    (root / ".app.env").write_text("API_URL=http://127.0.0.1:8000\n", encoding="utf-8")
    assert run_env_seams_check(root)[0] == 0


def test_a_container_resolved_service_name_passes(tmp_path: pathlib.Path) -> None:
    root = _project(
        tmp_path, declared={"API_URL": {"type": "string", "resolvedBy": "container"}}
    )
    (root / ".app.env").write_text("API_URL=http://api:8000\n", encoding="utf-8")
    assert run_env_seams_check(root)[0] == 0


def test_a_loopback_default_in_the_manifest_is_refused(tmp_path: pathlib.Path) -> None:
    """The manifest's own default lands when no seam supplies a value."""
    root = _project(
        tmp_path,
        declared={
            "API_URL": {
                "type": "string",
                "resolvedBy": "container",
                "default": "http://localhost:8000",
            }
        },
    )
    assert run_env_seams_check(root)[0] == 1


def test_loopback_recognises_the_forms_an_address_takes() -> None:
    assert _is_loopback("http://127.0.0.1:8000")
    assert _is_loopback("http://localhost:8000/path")
    assert _is_loopback("localhost:5432")
    assert _is_loopback("0.0.0.0")  # noqa: S104 - a value to DETECT, not to bind
    assert not _is_loopback("http://api:8000")
    assert not _is_loopback("db:5432")
    assert not _is_loopback("")


# --------------------------------------------------------------------------- #
# staying quiet when there is nothing to say
# --------------------------------------------------------------------------- #
def test_an_app_with_no_manifest_passes(tmp_path: pathlib.Path) -> None:
    """Upgrading the framework must not turn an app's gate red for an unfilled seam."""
    (tmp_path / "docker-compose.yml").write_text(
        _COMPOSE.format(environment="    ENVIRONMENT: local"), encoding="utf-8"
    )
    assert run_env_seams_check(tmp_path)[0] == 0


def test_an_app_declaring_nothing_passes(tmp_path: pathlib.Path) -> None:
    assert run_env_seams_check(_project(tmp_path, declared={}))[0] == 0


def test_an_unparsable_manifest_is_not_this_checks_verdict(
    tmp_path: pathlib.Path,
) -> None:
    """Studio fails the deploy closed on a broken manifest with a directive message.

    Turning the app's whole gate red here would report someone else's verdict badly.
    """
    root = _project(tmp_path, declared={})
    (root / "environment.schema.json").write_text("{not json", encoding="utf-8")
    assert run_env_seams_check(root)[0] == 0


def test_a_clean_app_reports_the_variables_that_do_arrive(
    tmp_path: pathlib.Path,
) -> None:
    root = _project(tmp_path, declared={"MY_VAR": {"type": "string"}})
    exit_code, output = run_env_seams_check(root)
    assert exit_code == 0
    assert "1 declared variable(s) reach the app" in output
