"""The ``terp migrate`` command line (also the standalone ``terp-migrate`` script).

Thin argument parsing over :mod:`terp.migrations.orchestrate` and the boot guard;
``terp.cli`` delegates its ``migrate`` subcommand here so the unified UX is
``terp migrate upgrade`` while the heavy Alembic dependency stays out of the kernel.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from collections.abc import Sequence

from sqlalchemy import create_engine

from terp.core import get_settings
from terp.migrations.errors import MigrationError, PendingMigrationsError
from terp.migrations.guard import assert_migrations_current
from terp.migrations.orchestrate import (
    adopt_schemas,
    downgrade,
    grant_runtime_role,
    heads,
    make,
    merge_heads,
    migration_status,
    stamp,
    upgrade,
    upgrade_sql,
)


def _resolve_app_root(value: str | None) -> pathlib.Path | None:
    """The app package dir holding ``modules/`` (default ``./app`` when present).

    An *explicit* ``--app-root`` that is not a directory fails closed: a typo must not
    silently degrade ``check`` / ``upgrade`` to installed capabilities only, skipping
    every app module. The *implicit* default ``./app`` being absent is fine and means
    "target installed capabilities only".
    """
    if value is None:
        default = pathlib.Path("app")
        return default if default.is_dir() else None
    candidate = pathlib.Path(value)
    if not candidate.is_dir():
        raise MigrationError(
            f"--app-root {value!r} is not a directory; pass the app package directory "
            "that holds modules/, or omit --app-root to target installed capabilities only"
        )
    return candidate


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--database-url",
        default=None,
        help="Database URL (default: settings.DATABASE_URL)",
    )
    parser.add_argument(
        "--app-root",
        default=None,
        help="App package dir holding modules/ (default: ./app when present)",
    )
    parser.add_argument(
        "--package", default="app", help="App import package (default: app)"
    )
    parser.add_argument(
        "--schema-layout",
        default=None,
        choices=("flat", "per-module"),
        help="Physical table layout (default: settings.DB_SCHEMA_LAYOUT; ADR 0070)",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="terp migrate", description="Run Terp's per-package migrations."
    )
    sub = parser.add_subparsers(dest="migrate_command", required=True)

    upgrade_parser = sub.add_parser("upgrade", help="Upgrade every package to head")
    upgrade_parser.add_argument("--revision", default="head")
    upgrade_parser.add_argument(
        "--sql",
        action="store_true",
        help="Render the upgrade as offline SQL on stdout instead of executing it "
        "(DBA-reviewable; nothing connects; flat layout only)",
    )
    _add_common(upgrade_parser)

    downgrade_parser = sub.add_parser(
        "downgrade", help="Downgrade every package (base/-N), or one with --label"
    )
    downgrade_parser.add_argument("--revision", default="base")
    downgrade_parser.add_argument(
        "--label",
        default=None,
        help="Downgrade only this package (then --revision may be any of its revisions)",
    )
    _add_common(downgrade_parser)

    make_parser = sub.add_parser("make", help="Author a new revision for one package")
    make_parser.add_argument("label", help="Package label (capability or app module)")
    make_parser.add_argument(
        "-m",
        "--message",
        default=None,
        help="Revision message (default: 'update <label>')",
    )
    make_parser.add_argument("--no-autogenerate", action="store_true")
    _add_common(make_parser)

    status_parser = sub.add_parser("status", help="Show current-vs-head per package")
    _add_common(status_parser)

    check_parser = sub.add_parser("check", help="Fail if any package is behind head")
    _add_common(check_parser)

    stamp_parser = sub.add_parser(
        "stamp", help="Baseline an existing DB: record head without running DDL"
    )
    stamp_parser.add_argument("--revision", default="head")
    _add_common(stamp_parser)

    heads_parser = sub.add_parser(
        "heads", help="Show head revision(s) per package (more than one = diverged)"
    )
    _add_common(heads_parser)

    merge_parser = sub.add_parser(
        "merge", help="Merge a package's multiple heads back into one"
    )
    merge_parser.add_argument("label", help="Package label (capability or app module)")
    merge_parser.add_argument("-m", "--message", required=True)
    _add_common(merge_parser)

    adopt_parser = sub.add_parser(
        "adopt-schemas",
        help="Move an existing flat database's tables into per-module schemas (ADR 0070)",
    )
    _add_common(adopt_parser)

    grant_parser = sub.add_parser(
        "grant-runtime",
        help="Grant least-privilege DML to an existing runtime login role (ADR 0071)",
    )
    grant_parser.add_argument(
        "role", help="Existing PostgreSQL login role the app connects as"
    )
    grant_parser.add_argument(
        "--owner-role",
        default=None,
        help="Role that runs `terp migrate` (ALTER DEFAULT PRIVILEGES FOR ROLE), "
        "when the grant is executed by a different admin role",
    )
    _add_common(grant_parser)

    return parser


def migrate_main(argv: Sequence[str] | None = None) -> None:
    """Entry point for ``terp migrate`` / the ``terp-migrate`` console script."""
    args = _build_parser().parse_args(argv)
    database_url = args.database_url or get_settings().DATABASE_URL
    try:
        app_root = _resolve_app_root(args.app_root)
    except MigrationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc

    if args.migrate_command == "upgrade":
        if args.sql:
            try:
                script = upgrade_sql(
                    database_url,
                    app_root,
                    package=args.package,
                    revision=args.revision,
                    schema_layout=args.schema_layout,
                )
            except MigrationError as exc:
                print(str(exc), file=sys.stderr)
                raise SystemExit(1) from exc
            print(script, end="")
            return
        applied = upgrade(
            database_url,
            app_root,
            package=args.package,
            revision=args.revision,
            schema_layout=args.schema_layout,
        )
        print(f"upgraded: {applied}")
        return
    if args.migrate_command == "downgrade":
        reverted = downgrade(
            database_url,
            app_root,
            package=args.package,
            revision=args.revision,
            label=args.label,
            schema_layout=args.schema_layout,
        )
        print(f"downgraded: {reverted}")
        return
    if args.migrate_command == "make":
        tree = make(
            args.label,
            args.message or f"update {args.label}",
            database_url,
            app_root,
            package=args.package,
            autogenerate=not args.no_autogenerate,
            schema_layout=args.schema_layout,
        )
        print(f"created revision for {tree.label} in {tree.versions_path}")
        return
    if args.migrate_command == "adopt-schemas":
        try:
            moved = adopt_schemas(database_url, app_root, package=args.package)
        except MigrationError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from exc
        for label, tables in moved.items():
            print(f"  {label:<16} -> {tables}")
        print(f"adopted: {sorted(moved)}")
        return
    if args.migrate_command == "grant-runtime":
        try:
            schemas = grant_runtime_role(
                database_url,
                args.role,
                app_root,
                package=args.package,
                schema_layout=args.schema_layout,
                owner_role=args.owner_role,
            )
        except MigrationError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from exc
        print(f"granted runtime DML to {args.role!r} on: {schemas}")
        return
    if args.migrate_command == "status":
        _print_status(database_url, app_root, args.package)
        return
    if args.migrate_command == "stamp":
        stamped = stamp(
            database_url,
            app_root,
            package=args.package,
            revision=args.revision,
            schema_layout=args.schema_layout,
        )
        print(f"stamped: {stamped}")
        return
    if args.migrate_command == "heads":
        _print_heads(database_url, app_root, args.package)
        return
    if args.migrate_command == "merge":
        tree = merge_heads(
            args.label, args.message, database_url, app_root, package=args.package
        )
        print(f"merged heads for {tree.label} in {tree.versions_path}")
        return
    _check(database_url, app_root, args.package)


def _print_status(
    database_url: str, app_root: pathlib.Path | None, package: str
) -> None:
    engine = create_engine(database_url)
    try:
        rows = migration_status(engine, app_root, package=package)
    finally:
        engine.dispose()
    for row in rows:
        marker = "ok" if row.is_current else "PENDING"
        print(f"  {row.label:<16} {marker:<8} current={row.current} head={row.head}")


def _print_heads(
    database_url: str, app_root: pathlib.Path | None, package: str
) -> None:
    for label, revs in heads(database_url, app_root, package=package).items():
        marker = "ok" if len(revs) <= 1 else "MULTIPLE HEADS"
        print(f"  {label:<16} {marker:<14} {revs}")


def _check(database_url: str, app_root: pathlib.Path | None, package: str) -> None:
    engine = create_engine(database_url)
    try:
        assert_migrations_current(engine, app_root, package=package)
    except PendingMigrationsError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        engine.dispose()
    print("migrations current")


__all__ = ["migrate_main"]
