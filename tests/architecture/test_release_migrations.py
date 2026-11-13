"""``outputs.migrations``: every history the backend image's upgrade brings to head, read as data.

ADR 0216. Each case starts from a tree of the fixture app and the sandbox's answer for an image
built faithfully from it, adds or changes what it is about, and expects the listing, or the
refusals that change earns. The capability case goes through the sandbox for real: the capabilities of this
repository that declare a history, laid out as their wheels install them, in a real layer.
"""

from __future__ import annotations

import base64
import hashlib
import json
import pathlib
import tomllib

import pytest

from terp.cli.release import _history, _image, _migrations, _sandbox
from terp.cli.release._git import Tree
from terp.cli.release._image import Node
from tests.architecture.release_fixtures import REPO_ROOT, app_files, committed_app, git
from tests.architecture.test_release_compare import SITE, faithful
from tests.architecture.test_release_image import FakeRegistry, layer

#: Where a test installs a capability: the environment's own site-packages, as a wheel lands.
CAPABILITY = "terp/capabilities/notes_cap"
DIST = f"{SITE}/terp_cap_notes-1.0.dist-info"
VERSIONS = f"{SITE}/{CAPABILITY}/migrations/versions"


def revision(rev: str, down: object = None, upgrade: str = "    pass\n", *, depends_on: object = None) -> bytes:
    """A revision file as Alembic's template writes it, with *upgrade* as its body."""
    return (
        '"""a revision"""\n'
        "from alembic import op\n"
        "import sqlalchemy as sa\n\n"
        f"revision: str = {rev!r}\n"
        f"down_revision: str | None = {down!r}\n"
        "branch_labels = None\n"
        f"depends_on = {depends_on!r}\n\n\n"
        "def upgrade() -> None:\n"
        f"{upgrade}\n\n"
        "def downgrade() -> None:\n"
        "    pass\n"
    ).encode()


def commit(tmp_path: pathlib.Path, files: dict[str, bytes] | None = None) -> Tree:
    """The fixture app with *files* beside its own, committed and read as ``sign`` reads it."""
    root = tmp_path / "repo"
    return Tree.read(root, committed_app(root, app_files() | (files or {})))


def with_paths(answer: dict, extra: dict[str, bytes | Node], drop: tuple[str, ...] = ()) -> dict:
    """*answer*, the sandbox's for a faithful image (:func:`faithful`), with *extra* paths in the image
    (bytes for a file, a node for anything else) and without *drop*, read again as the sandbox reads
    an image (:func:`_image.migration_inputs`)."""
    state = {path: Node.from_data(data) for path, data in answer["nodes"].items()}
    kept = {path: base64.b64decode(data) for path, data in answer["migrationInputs"]["files"].items()}
    for path, item in extra.items():
        if isinstance(item, bytes):
            state[path] = Node("file", hashlib.sha256(item).hexdigest(), len(item))
            if _image._KEPT.fullmatch(path):
                kept[path] = item
        else:
            state[path] = item
    for path in drop:
        state.pop(path)
        kept.pop(path, None)
    srv = {path: node.as_data() for path, node in sorted(state.items()) if path.startswith("srv/")}
    return {**answer, "nodes": srv, "migrationInputs": _image.migration_inputs(state, kept)}


def capability(revisions: dict[str, bytes], entry: str = "notes_cap = terp.capabilities.notes_cap\n") -> dict[str, bytes | Node]:
    """The paths a wheel of a capability declaring one history installs, its revisions among them."""
    return {
        f"{DIST}/entry_points.txt": (
            "# written by the build backend\n[terp.capabilities]\nnotes_cap = terp.capabilities.notes_cap:module\n\n"
            f"[terp.migrations]\n{entry}"
        ).encode(),
        f"{DIST}/METADATA": b"Name: terp-cap-notes\nVersion: 1.0\n",
        f"{SITE}/{CAPABILITY}/__init__.py": b"",
        **{f"{VERSIONS}/{name}": data for name, data in revisions.items()},
    }


def listed(tree: Tree, answer: dict) -> dict:
    findings, field = _migrations.migrations(tree, answer)
    assert findings == []
    return field


def refusals(tree: Tree, answer: dict) -> list[str]:
    findings, _field = _migrations.migrations(tree, answer)
    assert findings, "the reading refused nothing"
    return findings


# --------------------------------------------------------------------------- what is listed
#: A module's history: a base, a contract step with an excused and an unexcused drop and two drops
#: of one kind, a statement it cannot read, a merge, and a hotfix in a file whose name begins with
#: ``_``, which Alembic loads. ``__init__x.py`` and ``README.md`` are no revisions.
NOTES = {
    "app/modules/notes/__init__.py": b"",
    "app/modules/notes/migrations/versions/__init__.py": b"",
    "app/modules/notes/migrations/versions/a1_create_notes.py": revision(
        "a1", None, "    op.create_table('note', sa.Column('id', sa.Integer(), primary_key=True))\n"),
    "app/modules/notes/migrations/versions/b2_contract.py": revision("b2", "a1", (
        "    op.drop_column('note', 'legacy_ref')  # arch-allow-no-destructive-migrations: contract step after the backfill job\n"
        "    op.drop_column('note', 'draft')\n"
        "    op.drop_table('old_note')\n")),
    "app/modules/notes/migrations/versions/x2_backfill.py": revision("x2", "a1", (
        "    statement = \"UPDATE note SET body = ''\"\n"
        "    op.execute(statement)\n")),
    "app/modules/notes/migrations/versions/c3_merge.py": revision("c3", ("x2", "b2")),
    "app/modules/notes/migrations/versions/_d4_hotfix.py": revision(
        "d4", "c3", "    op.alter_column('note', 'body', type_=sa.Text())\n"),
    "app/modules/notes/migrations/versions/__init__x.py": revision("skipped", "d4"),
    "app/modules/notes/migrations/versions/README.md": b"how the notes history runs\n",
    "app/modules/_shared/migrations/versions/e5_private.py": revision("e5"),
    "app/modules/bare/__init__.py": b"",
    "app/modules/fresh/migrations/versions/__init__.py": b"",
}


def test_each_module_history_is_listed_from_the_tree_sorted(tmp_path: pathlib.Path) -> None:
    tree = commit(tmp_path, NOTES)
    field = listed(tree, faithful(tree))
    assert field == {
        "bare": {"revisions": [], "operations": []},
        "fresh": {"revisions": [], "operations": []},
        "notes": {
            "revisions": [
                {"id": "a1", "down": []},
                {"id": "b2", "down": ["a1"]},
                {"id": "c3", "down": ["b2", "x2"]},
                {"id": "d4", "down": ["c3"]},
                {"id": "x2", "down": ["a1"]},
            ],
            "operations": [
                {"revision": "b2", "ordinal": 1, "kind": "drop", "operation": "drop_column note.legacy_ref"},
                {"revision": "b2", "ordinal": 2, "kind": "drop", "operation": "drop_column note.draft"},
                {"revision": "b2", "ordinal": 3, "kind": "drop", "operation": "drop_table old_note"},
                {"revision": "d4", "ordinal": 1, "kind": "type", "operation": "alter_column note.body"},
                {"revision": "x2", "ordinal": 1, "kind": "opaque", "operation": "execute: ?"},
            ],
        },
    }, "a module named _shared is skipped by discovery, and so never runs"


def test_a_capability_history_is_read_from_its_installed_wheel(tmp_path: pathlib.Path, monkeypatch) -> None:
    """Every capability of this repository that declares a history, laid out as its wheel installs
    it in a real layer the sandbox reads: the histories hold three entries in all, the webhooks
    capability's type change and two statements of the audit capability its reading cannot see
    into, which a list read from the tree alone would have missed."""
    files: dict[str, bytes] = {}
    declared: dict[str, str] = {}
    for pyproject in sorted((REPO_ROOT / "packages" / "backend" / "capabilities").glob("*/pyproject.toml")):
        project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
        groups = project.get("entry-points", {})
        if "terp.migrations" not in groups:
            continue
        declared.update(groups["terp.migrations"])
        dist = f"{project['name'].replace('-', '_')}-{project['version']}.dist-info"
        files[f"{SITE}/{dist}/entry_points.txt"] = "".join(
            f"[{group}]\n" + "".join(f"{name} = {value}\n" for name, value in entries.items()) + "\n"
            for group, entries in groups.items()
        ).encode()
        source = pyproject.parent / "src"
        for path in sorted(source.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                files[f"{SITE}/{path.relative_to(source).as_posix()}"] = path.read_bytes()
    fake = FakeRegistry()
    pushed = fake.push_image([layer(*files.items())])
    monkeypatch.setattr(_sandbox, "egress_getter", lambda host, http: fake)
    tree = commit(tmp_path)
    answer = _sandbox.image_task({"repository": "registry.example/rel/app", "digest": pushed, "platform": "linux/amd64",
                                  "http": False, "credentials": None, "tree": str(tmp_path / "repo"), "base": None})
    field = listed(tree, json.loads(json.dumps(answer)))
    assert sorted(field) == sorted(declared) and len(field) >= 8
    for label, history in field.items():
        versions = pathlib.Path(REPO_ROOT, "packages", "backend", "capabilities", label, "src",
                                *declared[label].split("."), "migrations", "versions")
        assert {item["id"] for item in history["revisions"]} == {
            path.name.split("_")[0] for path in versions.glob("*.py") if path.name != "__init__.py"
        }, label
        assert sum(item["down"] == [] for item in history["revisions"]) == 1, f"{label} starts at one base"
        assert all(len(item["down"]) <= 1 for item in history["revisions"]), f"{label} is linear (ADR 0027)"
    operations = {label: history["operations"] for label, history in field.items() if history["operations"]}
    assert operations == {
        "audit": [
            {"revision": "3a9d71c5e40f", "ordinal": 1, "kind": "opaque", "operation": "execute: ?"},
            {"revision": "3a9d71c5e40f", "ordinal": 2, "kind": "opaque", "operation": "execute: ?"},
        ],
        "webhooks": [
            {"revision": "8f1c4a2d9b3e", "ordinal": 1, "kind": "type", "operation": "alter_column webhook_subscription.secret"},
        ],
    }


def test_a_capability_whose_package_has_no_versions_is_listed_with_no_revision(tmp_path: pathlib.Path) -> None:
    tree = commit(tmp_path)
    answer = with_paths(faithful(tree), capability({}) | {f"{VERSIONS}/__pycache__/x.pyc": b"", f"{VERSIONS}/notes.txt": b""})
    assert listed(tree, answer) == {"notes_cap": {"revisions": [], "operations": []}}
    assert listed(tree, with_paths(faithful(tree), capability({}))) == {"notes_cap": {"revisions": [], "operations": []}}


def test_an_entry_point_naming_an_attribute_and_an_egg_info_directory_are_read(tmp_path: pathlib.Path) -> None:
    tree = commit(tmp_path)
    paths = capability({"a1_x.py": revision("a1")}, "notes_cap = terp.capabilities.notes_cap:anything\n")
    paths = {path.replace(".dist-info", ".EGG-INFO"): data for path, data in paths.items()}
    answer = with_paths(faithful(tree), paths | {"usr/lib/python3/dist-packages/other-2.dist-info/entry_points.txt": b"[console_scripts]\nx = y:z\n"})
    assert listed(tree, answer) == {"notes_cap": {"revisions": [{"id": "a1", "down": []}], "operations": []}}


# --------------------------------------------------------------------------- where a history lies
def test_a_terp_migrations_section_outside_a_site_packages_distribution_is_refused(tmp_path: pathlib.Path) -> None:
    tree = commit(tmp_path)
    for where in ("srv/plugins/terp_cap_notes-1.0.dist-info/entry_points.txt", "srv/notes/entry_points.txt"):
        answer = with_paths(faithful(tree), {where: b"[terp.migrations]\nnotes_cap = terp.capabilities.notes_cap\n"})
        assert refusals(tree, answer) == [
            f"/{where} declares the migration histories notes_cap = terp.capabilities.notes_cap outside a "
            "distribution directory that sits directly in a site-packages or dist-packages directory, so "
            "sign cannot hold a history to the package the distribution installed: install the "
            "distribution as a wheel into the environment the app runs from"
        ]


def test_a_package_its_distribution_does_not_hold_in_place_is_refused(tmp_path: pathlib.Path) -> None:
    """An editable install: the distribution's metadata is in site-packages, its package elsewhere."""
    tree = commit(tmp_path)
    answer = with_paths(faithful(tree), capability({}) | {"src/terp/capabilities/notes_cap/__init__.py": b""},
                        drop=(f"{SITE}/{CAPABILITY}/__init__.py",))
    [refusal] = refusals(tree, answer)
    assert refusal.startswith(
        f"the migration history 'notes_cap' that /{DIST}/entry_points.txt declares names the package "
        f"terp.capabilities.notes_cap, and /{SITE}/{CAPABILITY}/ is no directory of the image: an "
        "editable install"
    )


@pytest.mark.parametrize("copy", ["srv/terp/capabilities/notes_cap/__init__.py", "terp/capabilities/notes_cap/x.py"])
def test_a_second_copy_of_a_capability_package_on_another_path_is_refused(tmp_path: pathlib.Path, copy: str) -> None:
    tree = commit(tmp_path)
    answer = with_paths(faithful(tree), capability({"a1_x.py": revision("a1")}) | {copy: b""})
    other = copy.rsplit("/", 1)[0]
    assert refusals(tree, answer) == [
        f"/{other} is a second copy of terp.capabilities.notes_cap, the package of the migration history "
        "'notes_cap': the interpreter imports whichever copy comes first on its path, so a copy under a "
        f"PYTHONPATH entry would run in place of /{SITE}/{CAPABILITY}/, the one sign read; remove it "
        "from the image"
    ]


@pytest.mark.parametrize(
    "entry",
    ["notes_cap terp.capabilities.notes_cap\n", "notes_cap = terp.capabilities.notes_cap [extra]\n",
     "notes_cap = terp.capabilities.notes-cap\n"],
)
def test_an_entry_point_in_another_form_is_refused(tmp_path: pathlib.Path, entry: str) -> None:
    tree = commit(tmp_path)
    [refusal] = refusals(tree, with_paths(faithful(tree), capability({}, entry)))
    assert refusal == (
        f"/{DIST}/entry_points.txt declares the migration history {entry.strip()!r}, which is not "
        "`label = import.path` or `label = import.path:attr`: declare the entry point in one of those forms"
    )


def _unreadable(path: str, what: str = "a symbolic link") -> str:
    return (
        f"{path} is {what} where sign reads a migration history: sign reads only files and directories "
        "there, and terp migrate upgrade would read through it to code no list names; put the file or "
        "the directory itself there"
    )


@pytest.mark.parametrize(
    ("extra", "drop", "refused"),
    [
        # The distribution, its entry points, the package, the way to it, its revisions.
        ({f"{SITE}/terp_cap_other-1.0.dist-info": Node("link", target="/opt/x.dist-info")}, (), f"{SITE}/terp_cap_other-1.0.dist-info"),
        ({f"{SITE}/other-1.0.dist-info/entry_points.txt": Node("link", target="/opt/e.txt")}, (), f"{SITE}/other-1.0.dist-info/entry_points.txt"),
        ({f"{SITE}/{CAPABILITY}": Node("link", target="/opt/notes_cap")}, (), f"{SITE}/{CAPABILITY}"),
        ({f"{SITE}/terp": Node("link", target="/opt/terp")}, (), f"{SITE}/terp"),
        ({f"{SITE}/{CAPABILITY}/migrations": Node("link", target="/opt/m")}, (f"{VERSIONS}/a1_x.py",), f"{SITE}/{CAPABILITY}/migrations"),
        ({VERSIONS: Node("link", target="/opt/v")}, (f"{VERSIONS}/a1_x.py",), VERSIONS),
        ({f"{VERSIONS}/b2.txt": Node("link", target="/opt/b2_y.py")}, (), f"{VERSIONS}/b2.txt"),
    ],
)
def test_a_link_where_the_capability_reading_passes_is_refused(tmp_path: pathlib.Path, extra, drop, refused: str) -> None:
    tree = commit(tmp_path)
    answer = with_paths(faithful(tree), capability({"a1_x.py": revision("a1")}) | extra, drop)
    assert _unreadable(f"/{refused}") in refusals(tree, answer)


def test_a_link_on_the_way_to_an_installed_package_is_refused(tmp_path: pathlib.Path) -> None:
    """A crafted layer can hold a link and paths below it: the reading never passes one."""
    tree = commit(tmp_path)
    answer = with_paths(faithful(tree), capability({}) | {"srv/.venv/lib": Node("link", target="/opt/lib")})
    assert refusals(tree, answer) == [_unreadable("/srv/.venv/lib")]


def test_anything_but_a_file_or_a_directory_among_the_revisions_is_refused(tmp_path: pathlib.Path) -> None:
    tree = commit(tmp_path)
    answer = with_paths(faithful(tree), capability({"a1_x.py": revision("a1")}) | {f"{VERSIONS}/b2_y.py": Node("other")})
    assert refusals(tree, answer) == [_unreadable(f"/{VERSIONS}/b2_y.py", "neither a file nor a directory")]


# --------------------------------------------------------------------------- the app's modules
@pytest.mark.parametrize(
    ("files", "refused"),
    [
        ({"app/modules/notes/migrations/versions": b"../../../../elsewhere\n"}, "app/modules/notes/migrations/versions"),
        ({"app/modules/notes": b"../../elsewhere\n"}, "app/modules/notes"),
        ({"app/modules/notes/migrations/versions/a1_x.py": b"../../../../../elsewhere/a1.py\n"}, "app/modules/notes/migrations/versions/a1_x.py"),
    ],
)
def _linked(tmp_path: pathlib.Path, links: dict[str, str], files: dict[str, bytes] | None = None) -> Tree:
    """The fixture app with *files*, and each path of *links* committed as a link to its target."""
    root = tmp_path / "repo"
    committed_app(root, files if files is not None else app_files())
    for path, target in links.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).symlink_to(target)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "links")
    return Tree.read(root, git(root, "rev-parse", "HEAD"))


@pytest.mark.parametrize(
    "link",
    ["app/modules/notes", "app/modules/notes/migrations/versions", "app/modules/notes/migrations/versions/a1_x.py"],
)
def test_a_link_where_the_module_reading_passes_is_refused(tmp_path: pathlib.Path, link: str) -> None:
    tree = _linked(tmp_path, {link: "/elsewhere"})
    assert tree.entries[link].link
    assert _unreadable(link) in refusals(tree, faithful(tree))


def test_the_app_modules_directory_as_a_link_is_refused(tmp_path: pathlib.Path) -> None:
    files = {path: data for path, data in app_files().items() if path != "app/modules/__init__.py"}
    tree = _linked(tmp_path, {"app/modules": "../elsewhere"}, files)
    assert refusals(tree, faithful(tree)) == [_unreadable("app/modules")]


def test_an_image_whose_modules_differ_from_the_tree_is_refused(tmp_path: pathlib.Path) -> None:
    tree = commit(tmp_path, {
        "app/modules/notes/migrations/versions/a1_x.py": revision("a1"),
        "app/modules/notes/migrations/versions/b2_y.py": revision("b2", "a1"),
        "app/modules/gone/__init__.py": b"",
    })
    answer = with_paths(faithful(tree), {
        "srv/app/modules/notes/migrations/versions/a1_x.py": revision("a1", None, "    op.drop_table('note')\n"),
        "srv/app/modules/notes/migrations/versions/c3_z.py": revision("c3", "b2"),
        "srv/app/modules/extra": Node("dir"),
        "srv/app/modules/_private": Node("dir"),
        "srv/app/modules/note.txt": b"",
    }, drop=("srv/app/modules/notes/migrations/versions/b2_y.py", "srv/app/modules/gone/__init__.py",
             "srv/app/modules/gone/__pycache__/__init__.cpython-314.pyc"))
    assert refusals(tree, answer) == [
        "/srv/app/modules/extra is a module of the image and none of the tree: terp migrate upgrade would "
        "bring it to head from code the gate never read; build the image from this commit",
        "app/modules/gone is a module of the tree, and the image holds no directory /srv/app/modules/gone: "
        "rebuild the image from this commit, with the module in its build context (.dockerignore)",
        "/srv/app/modules/notes/migrations/versions/a1_x.py is not the tree's "
        "app/modules/notes/migrations/versions/a1_x.py: the upgrade would run another revision than the "
        "one the gate read; rebuild the image from this commit",
        "app/modules/notes/migrations/versions/b2_y.py is a revision in the tree that the image does not "
        "hold: the gate read it, and the upgrade would not run it; rebuild the image from this commit, "
        "with the revision in its build context (.dockerignore)",
        "/srv/app/modules/notes/migrations/versions/c3_z.py is a revision in the image and none of the "
        "tree: the upgrade would run code the gate never read; build the image from this commit",
    ]


# --------------------------------------------------------------------------- one revision
def _module(files: dict[str, bytes]) -> dict[str, bytes]:
    return {f"app/modules/notes/migrations/versions/{name}": data for name, data in files.items()}


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        ({"a1_x.py": revision("b2-hotfix")},
         "app/modules/notes/migrations/versions/a1_x.py names the revision 'b2-hotfix', outside "
         "^[0-9A-Za-z_]{1,64}$, the ids a deploy's plan holds: give the revision an id of letters, "
         "digits and underscores (Alembic's own are twelve hexadecimal digits)"),
        ({"a1_x.py": revision("a1"), "b2_y.py": revision("b2", ("a1", "a 1"))},
         "app/modules/notes/migrations/versions/b2_y.py names the revision 'a 1', outside"),
        ({"a1_x.py": revision("a1"), "b2_y.py": revision("b2", ("a1", "a1"))},
         "app/modules/notes/migrations/versions/b2_y.py names 'a1' more than once in its down_revision: "
         "name each revision it follows once"),
        ({"a1_x.py": revision("a1", depends_on="z9")},
         "app/modules/notes/migrations/versions/a1_x.py sets depends_on to 'z9': Alembic then writes only "
         "the dependent revision to the version table, so a deploy that follows down_revision would count "
         "the other pending ever after, and a Terp history is linear (ADR 0027); order the two by "
         "down_revision and set depends_on to None"),
        ({"a1_x.py": revision("a1") + b"revision = 'a2'\n"},
         "app/modules/notes/migrations/versions/a1_x.py, a revision of the migration history 'notes', has "
         "a header sign cannot read for certain (the revision binds 'revision' 2 times at module level): "
         "assign revision, down_revision and depends_on once each, at the top level and to a literal, as "
         "Alembic's template writes them"),
        ({"a1_x.py": revision("a1") + b"depends_on = DEPENDS\n"},
         "has a header sign cannot read for certain (the revision binds 'depends_on' 2 times at module level)"),
        ({"a1_x.py": b"revision = 'a1'\ndown_revision = (\n"},
         "app/modules/notes/migrations/versions/a1_x.py, a revision of the migration history 'notes', is "
         "no Python source sign can parse ('(' was never closed, line 2): correct the file, which the "
         "upgrade would fail to load"),
        ({"a1_x.py": b"revision = 'a1'\ndown_revision = None\nNOTE = '\x00'\n"},
         "is no Python source sign can parse (source code string cannot contain null bytes)"),
        ({"a1_x.py": b"# -*- coding: nothing -*-\nrevision = 'a1'\n"},
         "app/modules/notes/migrations/versions/a1_x.py, a revision of the migration history 'notes', is "
         "no source text the interpreter can decode (unknown encoding: nothing): write it in UTF-8, as "
         "Alembic's template does; the upgrade would not load it either"),
        ({"a1_x.py": b"revision = 'a1'\ndown_revision = None\nNOTE = '\xff'\n"},
         "is no source text the interpreter can decode (its bytes are not utf-8)"),
        ({"a1_x.py": b"# coding: rot13\nrevision = 'a1'\n"},
         "is no source text the interpreter can decode (its coding declaration names no text encoding)"),
        ({"a1_x.py": b"# coding: undefined\nrevision = 'a1'\n"},
         "is no source text the interpreter can decode (its coding declaration names no text encoding)"),
        # Past what the parser holds: its stack, then the depth it builds a tree to.
        ({"a1_x.py": revision("a1", None, "    x = " + "-" * 100000 + "1\n")},
         "app/modules/notes/migrations/versions/a1_x.py, a revision of the migration history 'notes', "
         "nests too deeply for sign to read it: break up the expression that nests so deep"),
        ({"a1_x.py": revision("a1", None, "    x = a" + ".b" * 100000 + "\n")}, "nests too deeply for sign to read it"),
        ({"a1_x.py": revision("a1"), "b2_y.py": revision("a1")},
         "the migration history 'notes' has the revision 'a1' in app/modules/notes/migrations/versions/a1_x.py "
         "and app/modules/notes/migrations/versions/b2_y.py: give each revision an id of its own"),
        ({"b2_y.py": revision("b2", "a1")},
         "the revision 'b2' of the migration history 'notes' follows 'a1', which is no revision of that "
         "history: point its down_revision at one the history holds"),
        ({"a1_x.py": revision("a1", "c3"), "b2_y.py": revision("b2", "a1"), "c3_z.py": revision("c3", "b2")},
         "the migration history 'notes' runs in a cycle through down_revision (a1 -> c3 -> b2 -> a1, each "
         "following the next): a history starts at a revision that follows none, and each revision follows "
         "earlier ones"),
        ({"a1_x.py": revision("a1", "a1")}, "runs in a cycle through down_revision (a1 -> a1, each"),
    ],
)
def test_a_revision_a_deploy_cannot_hold_is_refused(tmp_path: pathlib.Path, files: dict[str, bytes], expected: str) -> None:
    tree = commit(tmp_path, _module(files))
    found = refusals(tree, faithful(tree))
    assert any(refusal.startswith(expected) or expected in refusal for refusal in found), found


def test_a_cycle_beside_a_merge_is_found_once_what_is_finished_is_left(tmp_path: pathlib.Path) -> None:
    files = {"a1_x.py": revision("a1"), "b2_y.py": revision("b2", "a1"), "c3_z.py": revision("c3", ("a1", "b2")),
             "d4_w.py": revision("d4", ("c3", "e5")), "e5_v.py": revision("e5", "d4")}
    tree = commit(tmp_path, _module(files))
    assert refusals(tree, faithful(tree)) == [
        "the migration history 'notes' runs in a cycle through down_revision (d4 -> e5 -> d4, each following "
        "the next): a history starts at a revision that follows none, and each revision follows earlier ones"
    ]


def test_a_cycle_is_named_by_its_ids_whatever_the_files_are_called(tmp_path: pathlib.Path) -> None:
    files = {"a_x.py": revision("r", "p"), "b_y.py": revision("q", "p"), "c_z.py": revision("p", ("r", "q"))}
    tree = commit(tmp_path, _module(files))
    assert refusals(tree, faithful(tree)) == [
        "the migration history 'notes' runs in a cycle through down_revision (p -> q -> p, each following "
        "the next): a history starts at a revision that follows none, and each revision follows earlier ones"
    ]


def test_what_a_deploy_s_plan_holds_bounds_the_listing(tmp_path: pathlib.Path, monkeypatch) -> None:
    tree = commit(tmp_path, _module({
        "a1_x.py": revision("a1", None, "    op.drop_table('a')\n    op.drop_table('b')\n"),
        "b2_y.py": revision("b2", "a1"), "c3_z.py": revision("c3", ("a1", "b2")),
    }) | {"app/modules/other/__init__.py": b""})
    monkeypatch.setattr(_history, "MOST_IN_HISTORY", 2)
    monkeypatch.setattr(_history, "MOST_PARENTS", 1)
    monkeypatch.setattr(_migrations, "MOST_HISTORIES", 1)
    assert refusals(tree, faithful(tree)) == [
        "the image holds 2 migration histories, more than the 1 a deploy's plan holds: fold modules that "
        "change together into one",
        "app/modules/notes/migrations/versions/c3_z.py follows 2 revisions, more than the 1 a deploy's plan "
        "holds for one revision: merge the heads in steps",
        "the migration history 'notes' lists 3 revisions, more than the 2 a deploy's plan holds for one "
        "history: squash its earliest revisions",
    ]
    monkeypatch.setattr(_history, "MOST_IN_HISTORY", 1)
    assert "the migration history 'notes' lists 2 operations, more than the 1 a deploy's plan holds for one " \
        "history: squash its earliest revisions" in refusals(tree, faithful(tree))


# --------------------------------------------------------------------------- labels
def test_two_histories_with_one_label_and_a_label_a_deploy_cannot_hold_are_refused(tmp_path: pathlib.Path) -> None:
    tree = commit(tmp_path, {"app/modules/notes_cap/__init__.py": b"", "app/modules/Notes/__init__.py": b""})
    answer = with_paths(faithful(tree), capability({}))
    assert refusals(tree, answer) == [
        "the migration history 'Notes', the module app/modules/Notes, has a label outside ^[a-z0-9_]{1,47}$: "
        "a deploy reads its version table alembic_version_<label>, and a table name holds 63 characters; "
        "name it with lower-case letters, digits and underscores",
        f"two migration histories are labelled 'notes_cap', the entry point in /{DIST}/entry_points.txt and "
        "the module app/modules/notes_cap: they would share the version table alembic_version_notes_cap, and "
        "terp migrate refuses them; rename one",
    ]
