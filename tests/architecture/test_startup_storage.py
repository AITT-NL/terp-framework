"""A process that cannot write its files does not start (ADR 0218).

An app rendered from the 0.34 template served every request but stored no file: its
production image ran as a user that could not write the files capability's storage root,
so each upload answered ``500`` and nothing before that said so. These tests pin the two
halves that close it. ``create_app`` runs every boot check a capability registered, and
outside ``ENVIRONMENT=local`` a storage root the process cannot write refuses the start
with one sentence that names the path, the cause and the remedy. And a filesystem failure
after the start is a typed ``502``, its cause in the log and never in the response.

On Windows ``chmod`` does not stop a write, so a root is made unwritable here the way that
works on every OS: its parent is a regular file.
"""

from __future__ import annotations

import io
import logging
import os
import pathlib
import textwrap
from collections.abc import Iterator
from typing import BinaryIO

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

import terp.core.boot_checks as boot_checks_module
from terp.core import BootError, ControlPlane, ModuleSpec, Policy, create_app
from terp.core._internal.session_guard import WriteGuardedSession
from terp.core.boot_checks import (
    BOOT_CHECK_ADR,
    boot_check_refusal,
    boot_checks,
    register_boot_check,
    unregister_boot_check,
)
from terp.core.config import settings

from terp.capabilities.files import (
    FileService,
    FileStorageError,
    LocalFilesystemStorage,
    StorageBackend,
    register_storage_backend,
    reset_storage_backend,
    set_storage_backend,
)
from terp.capabilities.files.storage import storage_boot_problem


@pytest.fixture(autouse=True)
def _restore_storage() -> Iterator[None]:
    yield
    reset_storage_backend()


@pytest.fixture
def project(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """A working directory of its own, as a project root or an image's ``/srv`` is."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _unwritable_root(base: pathlib.Path) -> pathlib.Path:
    """A root no process can create: its parent is a regular file, on every OS."""
    blocker = base / "srv-var"
    blocker.write_text("a file where a directory should be", encoding="utf-8")
    return blocker / "files"


def _deployed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")


def _app():
    return create_app(
        [ModuleSpec(name="probe", router=None, policy=Policy.default())],
        control_plane=ControlPlane(),
    )


def _logged(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(record.getMessage() for record in caplog.records)


class _NetworkStore(StorageBackend):
    """A store behind a provider: never called at boot (the base defaults)."""

    def put(self, key: str, source: BinaryIO) -> None:  # pragma: no cover - never called
        raise AssertionError("a boot check must not call a network store")

    def open(self, key: str) -> BinaryIO:  # pragma: no cover - never called
        raise AssertionError("a boot check must not call a network store")

    def delete(self, key: str) -> None:  # pragma: no cover - never called
        raise AssertionError("a boot check must not call a network store")


# --------------------------------------------------------------------------- #
# the refusal: a deployed process that cannot write its storage root
# --------------------------------------------------------------------------- #
def test_a_deployed_app_whose_storage_root_cannot_be_written_refuses_to_start(
    project: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _unwritable_root(project)
    set_storage_backend(LocalFilesystemStorage(root))
    _deployed(monkeypatch)
    with pytest.raises(BootError) as refused:
        _app()
    message = str(refused.value)
    assert message.startswith(f"files storage profile 'default': the storage root {root} ")
    assert "cannot be written (" in message
    assert "the app runs as " in message
    # The remedy, for the image and for an app rendered before the template had it.
    assert "make that directory writable by the user the app runs as" in message
    assert "mount a named volume there" in message
    assert "older than 0.35 re-renders it (`copier update`;" in message
    # A re-render brings the volume only with the use_files answer, so the remedy says how.
    assert "where it is false: `copier update --data use_files=true`" in message
    assert "mkdir -p /srv/var/files && chown appuser /srv/var/files" in message
    # Followed as written, the compose file must load: the mounted volume is declared too.
    assert "a `files-data:/srv/var/files` volume on `api` in docker-compose.prod.yml" in message
    assert "with `files-data:` under its top-level `volumes`" in message
    assert message.endswith("see: terp guide files")


def test_the_guides_hand_remedy_is_a_profile_that_declares_the_volume_it_mounts() -> None:
    """``terp guide files`` gives the production profile's lines to copy by hand. Followed as
    written they must leave a file Compose loads, and Compose refuses a named volume that a
    service mounts and the file does not declare under its top-level ``volumes``."""
    from terp.cli import _GUIDE_TOPICS

    lines = _GUIDE_TOPICS["files"].splitlines()
    start = next(i for i, line in enumerate(lines) if "the profile mounts the volume there" in line)
    snippet: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("      "):  # a snippet sits deeper than the bullet's prose
            snippet.append(line)
        elif snippet:
            break
    profile = yaml.safe_load(textwrap.dedent("\n".join(snippet)))
    assert profile["services"]["api"]["volumes"] == ["files-data:/srv/var/files"]
    mounted = {
        mount.split(":", 1)[0]
        for service in profile["services"].values()
        for mount in service.get("volumes", [])
    }
    assert mounted <= set(profile.get("volumes") or {}), "every mounted volume is declared"


def test_the_refusal_is_logged_the_way_a_deploy_reads_it(
    project: pathlib.Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Uncaught at import, a BootError is logged as ``uncaught BootError: <sentence>``.

    That line is what a deploy tool reads to show why the app did not start, so the
    sentence reaches it the way every other refusal does.
    """
    from terp.core._log_capture import _log_uncaught

    set_storage_backend(LocalFilesystemStorage(_unwritable_root(project)))
    _deployed(monkeypatch)
    with pytest.raises(BootError) as refused:
        _app()
    with caplog.at_level("CRITICAL", logger="terp.uncaught"):
        _log_uncaught(BootError, refused.value, refused.value.__traceback__)
    assert "uncaught BootError: files storage profile 'default': the storage root" in _logged(
        caplog
    )


def test_every_profile_is_asked_and_only_the_broken_one_is_named(
    project: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_storage_backend(LocalFilesystemStorage(project / "fine"))
    register_storage_backend("archive", LocalFilesystemStorage(_unwritable_root(project)))
    register_storage_backend("cloud", _NetworkStore())
    _deployed(monkeypatch)
    with pytest.raises(BootError) as refused:
        _app()
    message = str(refused.value)
    assert message.startswith("files storage profile 'archive': ")
    assert "'default'" not in message
    assert "'cloud'" not in message


def test_two_broken_profiles_are_each_named_on_a_line_of_their_own(
    project: pathlib.Path,
) -> None:
    set_storage_backend(LocalFilesystemStorage(_unwritable_root(project)))
    (project / "second").mkdir()
    register_storage_backend("archive", LocalFilesystemStorage(_unwritable_root(project / "second")))
    problem = storage_boot_problem()
    assert problem is not None
    lines = problem.splitlines()
    assert [line.split(":")[0] for line in lines] == [
        "files storage profile 'archive'",
        "files storage profile 'default'",
    ]


def test_the_sentence_names_the_uid_where_the_os_has_one(
    project: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = LocalFilesystemStorage(_unwritable_root(project))
    monkeypatch.setattr(os, "getuid", lambda: 10001, raising=False)
    assert "the app runs as uid 10001)" in (backend.boot_problem() or "")
    monkeypatch.delattr(os, "getuid")
    assert "the app runs as the current user)" in (backend.boot_problem() or "")


# --------------------------------------------------------------------------- #
# what starts
# --------------------------------------------------------------------------- #
def test_a_writable_root_is_created_probed_and_left_clean(
    project: pathlib.Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    root = project / "var" / "files"
    set_storage_backend(LocalFilesystemStorage(root))
    _deployed(monkeypatch)
    with caplog.at_level("INFO"):
        app = _app()
    assert TestClient(app).get("/health/live").status_code == 200
    assert root.is_dir()
    assert list(root.iterdir()) == []  # the probe file is gone again
    assert "boot checks passed: " in _logged(caplog)
    assert "files_storage" in _logged(caplog)


def test_a_store_behind_a_provider_is_not_called_at_boot(
    project: pathlib.Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    set_storage_backend(_NetworkStore())
    _deployed(monkeypatch)
    with caplog.at_level("WARNING"):
        _app()
    assert "files storage profile" not in _logged(caplog)


def test_in_development_an_unwritable_root_is_a_warning_and_the_app_starts(
    project: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    set_storage_backend(LocalFilesystemStorage(_unwritable_root(project)))
    with caplog.at_level("WARNING", logger="terp.core"):
        app = _app()
    assert TestClient(app).get("/health/live").status_code == 200
    logged = _logged(caplog)
    assert "files storage profile 'default': the storage root" in logged
    assert (
        f"Outside ENVIRONMENT=local this app refuses to start on this ({BOOT_CHECK_ADR})."
        in logged
    )


def test_in_development_a_passing_check_says_nothing(
    project: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    set_storage_backend(LocalFilesystemStorage(project / "files"))
    with caplog.at_level("INFO"):
        _app()
    logged = _logged(caplog)
    assert "boot checks passed" not in logged
    assert "files storage profile" not in logged


# --------------------------------------------------------------------------- #
# a root on the container's own disk: a warning when deployed, never a refusal
# --------------------------------------------------------------------------- #
def _stat_with_device(monkeypatch: pytest.MonkeyPatch, path: pathlib.Path, device: int) -> None:
    """Report *path* on device *device*, as a mounted volume is; every other path as is."""
    real_stat = os.stat

    class _Stat:
        def __init__(self, real: os.stat_result) -> None:
            self._real = real
            self.st_dev = device

        def __getattr__(self, name: str) -> object:
            return getattr(self._real, name)

    def _stat(target, *args, **kwargs):
        result = real_stat(target, *args, **kwargs)
        return _Stat(result) if pathlib.Path(target) == path else result

    monkeypatch.setattr(os, "stat", _stat)


def test_a_deployed_root_on_the_containers_own_disk_is_a_warning(
    project: pathlib.Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    root = project / "files"
    set_storage_backend(LocalFilesystemStorage(root))
    _deployed(monkeypatch)
    with caplog.at_level("WARNING", logger="terp.capabilities.files"):
        app = _app()
    assert TestClient(app).get("/health/live").status_code == 200
    logged = _logged(caplog)
    assert f"files storage profile 'default': the storage root {root.resolve()}" in logged
    assert "not on a mounted volume" in logged
    assert "Mount a named volume there" in logged


def test_a_deployed_root_on_a_mounted_volume_says_nothing(
    project: pathlib.Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    root = (project / "files").resolve()
    root.mkdir()
    backend = LocalFilesystemStorage(root)
    _stat_with_device(monkeypatch, root, device=os.stat(root.anchor).st_dev + 1)
    assert backend.boot_warning() is None
    set_storage_backend(backend)
    _deployed(monkeypatch)
    with caplog.at_level("WARNING", logger="terp.capabilities.files"):
        _app()
    assert "not on a mounted volume" not in _logged(caplog)


def test_in_development_a_root_on_the_local_disk_says_nothing(
    project: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    set_storage_backend(LocalFilesystemStorage(project / "files"))
    with caplog.at_level("WARNING", logger="terp.capabilities.files"):
        _app()
    assert "not on a mounted volume" not in _logged(caplog)


# --------------------------------------------------------------------------- #
# the registry in terp.core
# --------------------------------------------------------------------------- #
def test_the_files_capability_registers_its_check_on_import() -> None:
    assert boot_checks()["files_storage"] is storage_boot_problem


def test_registration_is_idempotent_and_refuses_a_second_check_under_one_name() -> None:
    def check() -> str | None:
        return None

    try:
        register_boot_check("test_check", check)
        register_boot_check("test_check", check)  # the same registration again
        with pytest.raises(ValueError, match="boot check 'test_check' is already registered"):
            register_boot_check("test_check", lambda: None)
        assert list(boot_checks()) == sorted(boot_checks())
    finally:
        unregister_boot_check("test_check")
    assert "test_check" not in boot_checks()
    unregister_boot_check("test_check")  # removing an absent check is a no-op


def test_a_check_that_cannot_run_refuses_rather_than_passing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken() -> str | None:
        raise RuntimeError("the probe itself broke")

    monkeypatch.setattr(boot_checks_module, "_checks", {"broken": broken})
    assert boot_check_refusal(local=False) == (
        "the boot check 'broken' could not run (RuntimeError: the probe itself broke)"
    )


def test_with_no_check_registered_a_deployed_process_says_nothing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """``boot checks passed`` is said only where a check ran, so it never means "none ran"."""
    monkeypatch.setattr(boot_checks_module, "_checks", {})
    with caplog.at_level("INFO", logger="terp.core"):
        assert boot_check_refusal(local=False) is None
    assert "boot checks passed" not in _logged(caplog)


# --------------------------------------------------------------------------- #
# after the start: a filesystem failure is a typed 502, its cause logged
# --------------------------------------------------------------------------- #
def test_a_put_into_an_unwritable_root_is_a_typed_storage_error(project: pathlib.Path) -> None:
    root = _unwritable_root(project)
    backend = LocalFilesystemStorage(root)
    with pytest.raises(FileStorageError) as failed:
        backend.put("ab/abc", io.BytesIO(b"bytes"))
    error = failed.value
    assert error.status_code == 502
    assert error.code == "file_storage_failed"
    assert str(root) not in error.message  # the client is told nothing about the disk
    assert error.log_context["operation"] == "put"
    assert error.log_context["root"] == str(root.resolve())
    assert error.log_context["key"] == "ab/abc"
    assert "Error" in error.log_context["error"]
    assert isinstance(error.__cause__, OSError)


def test_opening_what_is_not_a_blob_is_a_typed_storage_error(project: pathlib.Path) -> None:
    backend = LocalFilesystemStorage(project)
    (project / "ab" / "dir").mkdir(parents=True)
    with pytest.raises(FileStorageError) as failed:
        backend.open("ab/dir")
    assert failed.value.log_context["operation"] == "open"


def test_opening_an_unknown_key_stays_a_file_not_found(project: pathlib.Path) -> None:
    """The service answers this one with a 404, so it is not turned into a 502."""
    with pytest.raises(FileNotFoundError):
        LocalFilesystemStorage(project).open("ab/absent")


def test_deleting_what_is_not_a_blob_is_a_typed_storage_error(project: pathlib.Path) -> None:
    backend = LocalFilesystemStorage(project)
    (project / "ab" / "dir").mkdir(parents=True)
    with pytest.raises(FileStorageError) as failed:
        backend.delete("ab/dir")
    assert failed.value.log_context["operation"] == "delete"


class _BrokenStore(StorageBackend):
    """A store that fails every write and every cleanup, as one broken root does."""

    def put(self, key: str, source: BinaryIO) -> None:
        raise FileStorageError(log_context={"operation": "put"})

    def open(self, key: str) -> BinaryIO:  # pragma: no cover - never reached
        raise FileNotFoundError(key)

    def delete(self, key: str) -> None:
        raise FileStorageError(log_context={"operation": "delete"})


def test_a_failed_cleanup_never_replaces_the_uploads_own_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    set_storage_backend(_BrokenStore())
    with (
        WriteGuardedSession(engine) as session,
        caplog.at_level(logging.WARNING, logger="terp.capabilities.files"),
        pytest.raises(FileStorageError) as failed,
    ):
        FileService().store(
            session, filename="a.txt", content_type="text/plain", source=io.BytesIO(b"x")
        )
    engine.dispose()
    assert failed.value.log_context == {"operation": "put"}
    assert "could not remove the blob of a failed upload" in _logged(caplog)
