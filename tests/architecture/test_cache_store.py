"""Hot-read cache seam: shared backend, fail-closed boot guard, default unchanged.

Covers the kernel side of the quadruple (shaped like the throttle-store suite,
ADR 0036): the in-memory default's TTL/expiry semantics, the process-wide
``configure_cache`` / ``get_cache`` seam, the shared-store boot marker, and the
``create_app(cache_store=…, require_shared_cache_store=…)`` wiring — including the
fail-closed boot refusal of an unmarked per-instance store.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import APIRouter
from terp.core import (
    BootError,
    CacheStore,
    InMemoryCacheStore,
    ModuleSpec,
    Policy,
    configure_cache,
    create_app,
    get_cache,
    is_shared_cache_store,
    mark_shared_cache_store,
)


class _PassThrough(CacheStore):
    """Exercises the abstract bodies via ``super()`` (they are no-ops/None)."""

    def get(self, key: str) -> str | None:
        super().get(key)
        return None

    def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        super().set(key, value, ttl_seconds=ttl_seconds)

    def delete(self, key: str) -> None:
        super().delete(key)


@pytest.fixture(autouse=True)
def _reset_configured_cache() -> Iterator[None]:
    """Each test starts and ends with no configured process-wide store."""
    configure_cache(None)
    yield
    configure_cache(None)


def _spec() -> ModuleSpec:
    router = APIRouter()

    @router.get("/ping", response_model=str)
    def ping() -> str:
        return "pong"

    return ModuleSpec(name="probe", router=router, policy=Policy.public(reason="cache test"))


# --------------------------------------------------------------------------- #
# InMemoryCacheStore — the safe default
# --------------------------------------------------------------------------- #
def test_in_memory_set_get_expiry_lifecycle() -> None:
    now = [0.0]
    store = InMemoryCacheStore(clock=lambda: now[0])
    assert store.get("k") is None  # miss
    store.set("k", "v", ttl_seconds=60)
    assert store.get("k") == "v"  # live hit
    now[0] = 60  # TTL elapsed → expired on read
    assert store.get("k") is None
    assert store.get("k") is None  # the expired entry was dropped, still a miss


def test_in_memory_sweeps_expired_entries_on_write() -> None:
    now = [0.0]
    store = InMemoryCacheStore(clock=lambda: now[0])
    store.set("old-1", "v1", ttl_seconds=10)
    store.set("old-2", "v2", ttl_seconds=10)
    now[0] = 11
    store.set("new", "v3", ttl_seconds=10)

    assert store.get("old-1") is None
    assert store.get("old-2") is None
    assert store.get("new") == "v3"


def test_in_memory_sweep_is_interval_gated() -> None:
    """The write-path sweep is amortized: at most one full scan per interval.

    Sweeping on *every* set makes writes O(live entries) under the lock (~ms at
    100k entries, observed in load validation), so writes inside one interval skip
    the scan (expired entries linger, bounded by the interval) and the first write
    past the interval sweeps them.
    """
    now = [0.0]
    store = InMemoryCacheStore(clock=lambda: now[0])
    store.set("old", "v", ttl_seconds=1)  # first write sweeps; next sweep gated
    now[0] = 2  # "old" is expired, but the gate is still closed at +1s... reopen:
    store.set("within", "v", ttl_seconds=60)  # past the interval → sweeps "old"
    assert "old" not in store._entries
    now[0] = 2.5
    store.set("expired-fast", "v", ttl_seconds=60)
    store._entries["stale-probe"] = (2.4, "dead")  # expired, inside the gate window
    store.set("another", "v", ttl_seconds=60)  # gate closed → no scan, probe lingers
    assert "stale-probe" in store._entries
    assert store.get("stale-probe") is None  # but reads still expire it (never stale)
    now[0] = 4
    store.set("later", "v", ttl_seconds=60)  # gate reopened → sweep runs
    assert "stale-probe" not in store._entries


def test_in_memory_delete_and_reset() -> None:
    store = InMemoryCacheStore()
    store.set("k", "v", ttl_seconds=60)
    store.delete("k")
    assert store.get("k") is None
    store.delete("absent")  # a no-op, never raises
    store.set("k2", "v2", ttl_seconds=60)
    store.reset()
    assert store.get("k2") is None


def test_in_memory_set_requires_positive_ttl() -> None:
    store = InMemoryCacheStore()
    with pytest.raises(ValueError, match="positive ttl_seconds"):
        store.set("k", "v", ttl_seconds=0)
    with pytest.raises(ValueError, match="positive ttl_seconds"):
        store.set("k", "v", ttl_seconds=-1)


def test_abstract_bodies_are_callable() -> None:
    store = _PassThrough()
    assert store.get("k") is None
    store.set("k", "v", ttl_seconds=1)
    store.delete("k")


# --------------------------------------------------------------------------- #
# configure_cache / get_cache — the process-wide seam
# --------------------------------------------------------------------------- #
def test_get_cache_lazily_creates_the_in_memory_default() -> None:
    store = get_cache()
    assert isinstance(store, InMemoryCacheStore)
    assert get_cache() is store  # stable once created


def test_configure_cache_installs_and_resets_the_store() -> None:
    custom = InMemoryCacheStore()
    configure_cache(custom)
    assert get_cache() is custom
    configure_cache(None)
    assert get_cache() is not custom  # reset → a fresh lazy default


# --------------------------------------------------------------------------- #
# The shared-store boot marker
# --------------------------------------------------------------------------- #
def test_shared_marker_roundtrip() -> None:
    store = InMemoryCacheStore()
    assert is_shared_cache_store(store) is False
    assert is_shared_cache_store(None) is False
    marked = mark_shared_cache_store(store)
    assert marked is store
    assert is_shared_cache_store(store) is True


# --------------------------------------------------------------------------- #
# create_app wires the seam (fail-closed guard; default unchanged)
# --------------------------------------------------------------------------- #
def test_create_app_installs_the_supplied_cache_store() -> None:
    custom = InMemoryCacheStore()
    create_app([_spec()], cache_store=custom)
    assert get_cache() is custom


def test_create_app_without_a_cache_store_keeps_the_lazy_default() -> None:
    create_app([_spec()])
    assert isinstance(get_cache(), InMemoryCacheStore)


def test_boot_refuses_an_unmarked_store_when_a_shared_cache_is_required() -> None:
    # Fail closed: a multi-instance promise with a per-instance backend refuses to boot…
    with pytest.raises(BootError, match="require_shared_cache_store"):
        create_app([_spec()], cache_store=InMemoryCacheStore(), require_shared_cache_store=True)
    with pytest.raises(BootError, match="require_shared_cache_store"):
        create_app([_spec()], require_shared_cache_store=True)  # …and so does no store at all.


def test_boot_accepts_a_marked_shared_store() -> None:
    shared = mark_shared_cache_store(InMemoryCacheStore())
    create_app([_spec()], cache_store=shared, require_shared_cache_store=True)
    assert get_cache() is shared
