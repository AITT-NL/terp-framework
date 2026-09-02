"""The deployment safety envelope constrains properties, never topology.

Read the "must never be red" half first. The risk an enforced check on a deploy
profile carries is not that it misses an exposed database — it is that it
quietly becomes a gate on how people are allowed to deploy, which is the one
freedom this platform deliberately leaves ungated (ADR 0013, and ADR 0111
decision 6 on why safety is nonetheless the exception).

The other half is red on purpose, and both entries are irreversible: a
datastore reachable from outside is how application data leaves a deployment,
and a credential written into a compose file is in version control, in every
clone, and in the history for ever. Neither is fixable after the fact, which is
what makes conformance the right instrument here and truth-about-self the right
one for the inner loop.
"""

from __future__ import annotations

import pathlib
import re

import yaml

from terp.cli.deploy_safety import (
    ALLOW_FIELD,
    DEPLOY_PROFILES,
    audit,
    run_deploy_safety_check,
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _app(tmp_path: pathlib.Path, compose: dict) -> pathlib.Path:
    root = tmp_path / "app"
    root.mkdir(exist_ok=True)
    (root / DEPLOY_PROFILES[0]).write_text(yaml.safe_dump(compose), encoding="utf-8")
    return root


def _invariants(compose: dict) -> list[str]:
    return sorted(finding.invariant for finding in audit(compose))


# --- what must never be red ------------------------------------------------


def test_an_app_with_no_deployment_profile_passes(tmp_path) -> None:
    """Adopting the toolchain must never redden a gate over a file the app has
    not got. The same no-op success every generator-backed check gives."""
    root = tmp_path / "app"
    root.mkdir()

    code, output = run_deploy_safety_check(root)

    assert code == 0
    assert "nothing to check" in output


def test_the_number_and_kind_of_services_is_never_asked(tmp_path) -> None:
    """Any shape at all. This is the assertion that keeps the envelope from
    becoming a permitted-topology gate."""
    compose = {
        "services": {
            "web": {"image": "nginx", "ports": ["443:443"]},
            "api-one": {"image": "app-backend"},
            "api-two": {"image": "app-backend"},
            "api-three": {"image": "app-backend"},
            "worker": {"image": "app-backend", "command": ["python", "-m", "worker"]},
            "clamav": {"image": "clamav/clamav"},
            "waf": {"image": "owasp/modsecurity"},
            "sftp": {"image": "atmoz/sftp", "ports": ["2222:22"]},
        }
    }

    assert _invariants(compose) == []


def test_an_app_with_no_database_of_ours_is_fine(tmp_path) -> None:
    """A managed cloud database, or somebody else's estate. The absence of a
    service we happen to ship is never a finding."""
    compose = {"services": {"api": {"image": "app-backend"}}}

    assert _invariants(compose) == []


def test_a_datastore_that_publishes_nothing_is_fine() -> None:
    compose = {"services": {"db": {"image": "postgres:17-alpine"}}}

    assert _invariants(compose) == []


def test_a_non_datastore_may_publish_freely() -> None:
    """Publishing is how an app is reached. Only *datastores* are the question."""
    compose = {
        "services": {
            "web": {"image": "app-frontend", "ports": ["${WEB_PORT:-8080}:8080"]},
            "api": {"image": "app-backend", "ports": ["8000:8000"]},
        }
    }

    assert _invariants(compose) == []


def test_a_secret_taken_from_the_environment_is_fine() -> None:
    compose = {
        "services": {
            "api": {
                "image": "app-backend",
                "environment": {
                    "SECRET_KEY": "${SECRET_KEY:?SECRET_KEY is required}",
                    "POSTGRES_PASSWORD": "${POSTGRES_PASSWORD}",
                    "API_TOKEN": "",
                },
            }
        }
    }

    assert _invariants(compose) == []


def test_the_docker_secrets_convention_is_not_punished() -> None:
    """``*_FILE`` names a path to the credential, not the credential. Flagging
    it would push people off the safe pattern, which is the opposite of the
    point."""
    compose = {
        "services": {
            "api": {
                "image": "app-backend",
                "environment": {"SECRET_KEY_FILE": "/run/secrets/secret_key"},
            }
        }
    }

    assert _invariants(compose) == []


def test_an_ordinary_setting_that_merely_mentions_a_key_is_not_a_secret() -> None:
    """The name match is deliberately narrow. A gate that fires on half of
    every compose file teaches people to reach for the escape hatch, and then
    it means nothing."""
    compose = {
        "services": {
            "api": {
                "image": "app-backend",
                "environment": {
                    "WEB_PORT": "8080",
                    "DATABASE_URL": "postgresql://app@db:5432/app",
                    "KEYCLOAK_URL": "https://sso.example",
                    "PUBLIC_KEY_PATH": "/etc/ssl/pub.pem",
                },
            }
        }
    }

    assert _invariants(compose) == []


# --- what must be red ------------------------------------------------------


def test_a_published_datastore_is_refused() -> None:
    compose = {
        "services": {"db": {"image": "postgres:17-alpine", "ports": ["5432:5432"]}}
    }

    assert _invariants(compose) == ["published-datastore"]


def test_an_ephemeral_port_on_a_datastore_is_still_exposure() -> None:
    """Unlike the workbench check, the question here is reachability rather
    than collision — an ephemeral host port is still a host port."""
    compose = {"services": {"cache": {"image": "redis:7", "ports": ["6379"]}}}

    assert _invariants(compose) == ["published-datastore"]


def test_a_datastore_from_a_private_registry_is_recognised() -> None:
    compose = {
        "services": {
            "db": {
                "image": "registry.example.com/mirror/postgres:16@sha256:abc",
                "ports": [{"published": 5432, "target": 5432}],
            }
        }
    }

    assert _invariants(compose) == ["published-datastore"]


def test_a_literal_credential_is_refused() -> None:
    compose = {
        "services": {
            "api": {"image": "app-backend", "environment": {"SECRET_KEY": "hunter2"}}
        }
    }

    assert _invariants(compose) == ["literal-secret"]


def test_a_literal_credential_in_the_list_form_is_refused() -> None:
    """Compose accepts both forms and an agent writes whichever it saw last."""
    compose = {
        "services": {
            "api": {"image": "app-backend", "environment": ["POSTGRES_PASSWORD=hunter2"]}
        }
    }

    assert _invariants(compose) == ["literal-secret"]


def test_a_weak_default_credential_is_refused() -> None:
    """The version of this mistake that survives review.

    ``${SECRET_KEY:-changeme}`` reads as an interpolation and ships a known
    credential whenever the variable is unset, which is precisely the case
    nobody tests.
    """
    compose = {
        "services": {
            "api": {
                "image": "app-backend",
                "environment": {"SECRET_KEY": "${SECRET_KEY:-changeme}"},
            }
        }
    }

    assert _invariants(compose) == ["literal-secret"]


def test_a_required_interpolation_is_not_a_weak_default() -> None:
    """``:?`` is an error message, not a fallback. The fixture the previous
    assertion has to be able to tell apart."""
    compose = {
        "services": {
            "api": {
                "image": "app-backend",
                "environment": {"SECRET_KEY": "${SECRET_KEY:?required}"},
            }
        }
    }

    assert _invariants(compose) == []


def test_an_interpolated_default_is_not_a_literal() -> None:
    """``${A:-${B}}`` defers to another variable rather than baking a value."""
    compose = {
        "services": {
            "api": {
                "image": "app-backend",
                "environment": {"API_TOKEN": "${API_TOKEN:-${FALLBACK_TOKEN}}"},
            }
        }
    }

    assert _invariants(compose) == []


# --- the escape ------------------------------------------------------------


def test_an_accepted_risk_with_a_reason_is_allowed() -> None:
    compose = {
        "services": {
            "db": {
                "image": "postgres:17-alpine",
                "ports": ["5432:5432"],
                ALLOW_FIELD: {
                    "published-datastore": "single-tenant appliance, private VLAN"
                },
            }
        }
    }

    assert _invariants(compose) == []


def test_an_accepted_risk_without_a_reason_is_not_an_escape() -> None:
    """An escape nobody can review is a hole."""
    compose = {
        "services": {
            "db": {
                "image": "postgres:17-alpine",
                "ports": ["5432:5432"],
                ALLOW_FIELD: {"published-datastore": "   "},
            }
        }
    }

    assert _invariants(compose) == ["published-datastore"]


def test_an_escape_excuses_only_the_invariant_it_names() -> None:
    compose = {
        "services": {
            "db": {
                "image": "postgres:17-alpine",
                "ports": ["5432:5432"],
                "environment": {"POSTGRES_PASSWORD": "hunter2"},
                ALLOW_FIELD: {"published-datastore": "private VLAN"},
            }
        }
    }

    assert _invariants(compose) == ["literal-secret"]


def test_an_escape_excuses_only_the_service_it_sits_on() -> None:
    compose = {
        "services": {
            "db": {
                "image": "postgres:17-alpine",
                "ports": ["5432:5432"],
                ALLOW_FIELD: {"published-datastore": "private VLAN"},
            },
            "cache": {"image": "redis:7", "ports": ["6379:6379"]},
        }
    }

    assert _invariants(compose) == ["published-datastore"]


# --- the shipped artifacts -------------------------------------------------


def test_the_template_deployment_profile_satisfies_its_own_envelope() -> None:
    """The profile every app deploys from has to pass the gate it ships with.

    It is Jinja and does not parse as YAML, so this strips the wizard's
    conditional blocks the way test_compose_workbench.py does — the same reason,
    and the same limitation: the toggled-on renders are covered by the
    template-acceptance matrix.
    """
    text = (
        _REPO_ROOT / "template" / "project" / "docker-compose.prod.yml.jinja"
    ).read_text(encoding="utf-8")
    text = text.replace("{{ project_slug }}", "app").replace(
        "{{ project_name }}", "App"
    )
    text = re.sub(
        r"\{%-?\s*if\b.*?%\}.*?\{%-?\s*endif\s*-?%\}", "", text, flags=re.DOTALL
    )
    assert "{%" not in text, "unstripped Jinja block in the deployment profile"

    assert audit(yaml.safe_load(text)) == []


def test_the_check_reads_the_deployment_profile_and_says_so(tmp_path) -> None:
    root = _app(
        tmp_path,
        {
            "services": {
                "db": {"image": "postgres:17-alpine"},
                "web": {"image": "app-frontend", "ports": ["8080:8080"]},
            }
        },
    )

    code, output = run_deploy_safety_check(root)

    assert code == 0
    assert DEPLOY_PROFILES[0] in output


def test_an_unparsable_deployment_profile_is_refused_rather_than_skipped(
    tmp_path,
) -> None:
    root = tmp_path / "app"
    root.mkdir()
    (root / DEPLOY_PROFILES[0]).write_text("services: [oh: no: yes", encoding="utf-8")

    assert run_deploy_safety_check(root)[0] == 1


def test_the_refusal_says_it_is_not_about_shape(tmp_path) -> None:
    """The message is the interface. Somebody meeting this gate for the first
    time has to learn that their architecture is not the problem."""
    root = _app(
        tmp_path,
        {"services": {"db": {"image": "postgres:17", "ports": ["5432:5432"]}}},
    )

    code, output = run_deploy_safety_check(root)

    assert code == 1
    assert "never shape" in output
    assert ALLOW_FIELD in output, "the escape has to be discoverable from the failure"


# --- a profile that is not shaped like a compose file ----------------------
#
# These are the branches that decide what happens when the YAML parses but is
# not what it claims to be. A deployment gate that raises on a malformed file
# tells somebody their app is broken in a way it is not, so each one is a
# deliberate "nothing to say" rather than an error — and each needs a case,
# because an unexercised branch in a security check is a branch nobody has
# ever seen run.


def test_a_profile_with_no_services_block_has_nothing_to_check() -> None:
    assert audit({"version": "3.9"}) == []
    assert audit({"services": "not a mapping"}) == []


def test_a_service_that_is_not_a_mapping_is_skipped_not_crashed_on() -> None:
    """`services: {db: null}` parses fine and describes nothing."""
    compose = {
        "services": {
            "db": None,
            "cache": {"image": "redis:7", "ports": ["6379:6379"]},
        }
    }

    assert _invariants(compose) == ["published-datastore"]


def test_an_escape_whose_reason_is_not_text_is_not_an_escape() -> None:
    """`published-datastore: true` is somebody agreeing with themselves.

    A reason has to be reviewable, and a boolean reviews as nothing — so this
    takes the same path as a blank one rather than being read as consent.
    """
    compose = {
        "services": {
            "db": {
                "image": "postgres:17-alpine",
                "ports": ["5432:5432"],
                ALLOW_FIELD: {"published-datastore": True},
            }
        }
    }

    assert _invariants(compose) == ["published-datastore"]


def test_an_allow_field_that_is_not_a_mapping_excuses_nothing() -> None:
    compose = {
        "services": {
            "db": {
                "image": "postgres:17-alpine",
                "ports": ["5432:5432"],
                ALLOW_FIELD: "published-datastore",
            }
        }
    }

    assert _invariants(compose) == ["published-datastore"]


def test_a_service_built_from_a_dockerfile_names_no_image_family() -> None:
    """`build:` without `image:` is an ordinary way to write a service.

    Nothing can be concluded about what such a service runs, so it is not a
    datastore as far as this check is concerned — the honest reading, and the
    one that keeps the envelope from guessing. Its credentials are still
    checked, which is what distinguishes "we cannot identify this" from "we are
    not looking at this."
    """
    compose = {
        "services": {
            "api": {
                "build": {"context": ".", "dockerfile": "Dockerfile"},
                "ports": ["8000:8000"],
                "environment": {"SECRET_KEY": "hunter2"},
            }
        }
    }

    assert _invariants(compose) == ["literal-secret"]
