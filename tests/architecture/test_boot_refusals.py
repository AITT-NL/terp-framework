"""A refused start names everything that refuses it, not one thing per start (ADR 0222).

``create_app`` asks every question about an app's declarations before it configures
anything, and each check raised at its first finding. An app behind on several of them
learned of one per start: friction reported from upgrading an app across many releases
met a public module's undeclared route, fixed it, started again, and only then met the
timestamps that needed their UTC offset. They are independent questions, so they are now
answered together:

* several refusals are one ``BootError`` that numbers each, with each on ``refusals``;
* one refusal reads exactly as it always did, so nothing that reads it has to change;
* a refusal followed by a check that cannot run says where the checks stopped;
* nothing is configured while anything is refused.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import APIRouter, FastAPI

from terp.core import BootError, ModuleSpec, Policy, create_app, route_policy
from terp.core._boot_refusals import Refusals
from terp.core.route_timestamps import module_timestamps_refusal, request_timestamps_refusal


def _undeclared_public() -> ModuleSpec:
    """A public module with a route that says nothing of its own (ADR 0148)."""
    router = APIRouter()

    @router.post("/")
    def act() -> dict[str, str]:
        return {}

    return ModuleSpec(name="widgets", router=router, policy=Policy.public_write(reason="login endpoint"))


def _plain_timestamp() -> ModuleSpec:
    """A route that reads a timestamp with nothing to hold it to its offset (ADR 0208)."""
    router = APIRouter()

    @router.get("/")
    def since(after: datetime | None = None) -> dict[str, str]:
        return {}

    return ModuleSpec(name="events", router=router, policy=Policy.default())


def test_the_refusals_an_upgrade_met_one_start_at_a_time_arrive_together() -> None:
    with pytest.raises(BootError) as caught:
        create_app([_undeclared_public(), _plain_timestamp()])

    message = str(caught.value)
    assert message.startswith("2 things stop this app from starting")
    assert "1. " in message and "2. " in message
    assert "declares no policy of its own" in message
    # Named as it would be served, which is how the check after mounting names it too.
    assert "GET /api/v1/events/ reads a timestamp in the query parameter 'after'" in message
    refusals = caught.value.refusals  # type: ignore[attr-defined]
    assert len(refusals) == 2
    assert any("declares no policy of its own" in refusal for refusal in refusals)


def test_one_refusal_reads_exactly_as_it_always_did() -> None:
    # The sentence a deploy tool reads out of a refused start's log is unchanged, and the
    # error is the check's own, with its own cause.
    with pytest.raises(BootError) as caught:
        create_app([_undeclared_public()])

    message = str(caught.value)
    assert not message.startswith("1 things")
    assert "declares no policy of its own" in message
    assert caught.value.refusals == (message,)  # type: ignore[attr-defined]


def _served(*specs: ModuleSpec) -> FastAPI:
    """The specs' routers mounted where create_app mounts them, guards aside."""
    app = FastAPI()
    for spec in specs:
        if spec.router is not None:
            app.include_router(spec.router, prefix=f"/api/v1/{spec.name}")
    return app


def test_a_timestamp_alone_is_refused_in_the_words_of_the_check_after_mounting() -> None:
    spec = _plain_timestamp()
    with pytest.raises(BootError) as caught:
        create_app([spec])

    assert str(caught.value) == request_timestamps_refusal(_served(spec).routes)
    assert "GET /api/v1/events/" in str(caught.value)


def test_the_check_after_mounting_still_refuses_what_the_early_one_did_not_see(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The early check reads the modules' routers; the one after mounting reads every route
    # the app serves, the framework's own included (ADR 0208). It stays the backstop: a route
    # the early reading missed is still refused before the app is returned.
    monkeypatch.setattr("terp.core.app.module_timestamps_refusal", lambda specs: None)
    spec = _plain_timestamp()
    with pytest.raises(BootError) as caught:
        create_app([spec])
    assert str(caught.value) == request_timestamps_refusal(_served(spec).routes)


def test_a_router_not_yet_mounted_is_read_as_it_will_be_served() -> None:
    # A module router that includes routers of its own: each route under every prefix.
    inner = APIRouter()

    @inner.get("/{day}")
    def on(day: datetime) -> dict[str, str]:
        return {}

    outer = APIRouter()
    outer.include_router(inner, prefix="/days")
    specs = [
        ModuleSpec(name="calendar", router=outer, policy=Policy.default()),
        ModuleSpec(name="empty", policy=Policy.default()),
    ]

    found = module_timestamps_refusal(specs)

    assert found == request_timestamps_refusal(_served(*specs).routes)
    assert found is not None and "GET /api/v1/calendar/days/{day}" in found
    assert module_timestamps_refusal([ModuleSpec(name="empty", policy=Policy.default())]) is None


def test_the_production_refusals_arrive_together(monkeypatch: pytest.MonkeyPatch) -> None:
    from terp.core import ControlPlane, PasswordPolicy
    from terp.core.config import settings

    # The default security config allows no browser origin, which production refuses, and
    # a six-character password floor is a second, unrelated refusal.
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    plane = ControlPlane(passwords=PasswordPolicy(min_length=6))
    with pytest.raises(BootError) as caught:
        create_app([], control_plane=plane)

    message = str(caught.value)
    assert "insecure production security config" in message
    assert "insecure production password policy" in message


def test_a_check_that_cannot_run_after_a_refusal_says_where_the_checks_stopped() -> None:
    refusals = Refusals(BootError)
    with pytest.raises(BootError) as caught:
        with refusals:
            refusals.add("the first thing")
            raise KeyError("a module the first thing left undeclared")

    message = str(caught.value)
    assert message.startswith("1 thing stops this app from starting:\n1. the first thing")
    assert "The checks after these stopped at KeyError" in message
    assert isinstance(caught.value.__cause__, KeyError)


def test_an_error_before_any_refusal_is_left_as_it_is() -> None:
    with pytest.raises(KeyError):
        with Refusals(BootError):
            raise KeyError("no refusal was kept, so this is not about one")


def test_a_refusal_raised_inside_the_checks_joins_the_ones_kept_and_ends_them() -> None:
    refusals = Refusals(BootError)
    with pytest.raises(BootError) as caught:
        with refusals:
            refusals.add("kept")
            raise BootError("raised")
    assert caught.value.refusals == ("kept", "raised")  # type: ignore[attr-defined]


def test_nothing_is_configured_while_anything_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    configured: list[str] = []
    monkeypatch.setattr("terp.core.app.configure_audit", lambda *a, **k: configured.append("audit"))
    with pytest.raises(BootError):
        create_app([_undeclared_public(), _plain_timestamp()])
    assert configured == []


def test_an_app_with_nothing_refused_starts_as_before() -> None:
    router = APIRouter()

    @router.get("/")
    @route_policy(Policy.public(reason="a fixture"))
    def page() -> dict[str, str]:
        return {}

    app = create_app([ModuleSpec(name="pages", router=router, policy=Policy.public(reason="a fixture"))])
    assert app.title == "Terp app"
