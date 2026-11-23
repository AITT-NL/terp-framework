"""The two upgrade recipes ``terp upgrade --check`` prints, and the steps they share.

An app the template rendered re-renders and gets its pins written for it; an app that
cannot re-render writes them by hand. ``version.render_upgrade_check`` decides which one
an app gets and prints it; the recipes themselves live here, apart from the version
report they used to share a file with.
"""

from __future__ import annotations


def render_step(number: int) -> list[str]:
    """The step a generated app's upgrade adds once the new release is installed."""
    return [
        f"  {number}. uv run terp deployment render   (deployment.json says \"build\":",
        '     "generated": the template leaves Dockerfile.prod, frontend/Dockerfile.prod',
        "     and docker-compose.prod.yml to the new release's generator. Commit what it",
        "     writes; a missed render is red under `terp verify --only generated`.)",
    ]


def suite_install(conformance: bool) -> list[str]:
    """The conformance suite's install, for an app that has one.

    Its lock is committed like the frontend's, and every release moves the
    ``@terpjs/conformance`` pin in its manifest. CI installs the suite with ``npm ci``,
    which refuses a lock the new pin left behind, so the upgrade re-locks it too.
    """
    if not conformance:
        return []
    return [
        "     npm --prefix conformance install",
        "     (commit conformance/package-lock.json with the rest: CI installs the suite",
        "     from it with npm ci, which refuses a lock the new pins left behind.)",
    ]


def rerender_recipe(
    target: str, current: str, count: int, *, generated: bool = False, conformance: bool = False
) -> list[str]:
    """The upgrade for an app the template rendered: re-render first, sync once.

    The order used to be the other way round and could not be followed as printed.
    Steps 2 to 4 were "edit the pins, uv sync, npm install", and the re-render came
    after them — but ``copier update`` refuses a dirty tree, so the recipe's own
    earlier steps made its last step impossible, and whoever followed it had to stash
    halfway through.

    Worse, those pin edits were work the re-render does. The template owns
    ``pyproject.toml``, ``frontend/package.json`` and ``conformance/package.json``, so
    a re-render writes every one of those pins itself. The old recipe even warned that
    "a recipe that names only one is how the other goes stale" — which is an admission
    that the hand-pinning step was a footgun, for a job already done one step later.

    So: read, clean the tree, re-render, resolve, sync once, confirm, verify. A generated
    app renders its build files between the sync and the confirmation (ADR 0187): the
    template no longer writes them, and the release just installed has the generator.
    """
    render = render_step(6) if generated else []
    after = 7 if generated else 6
    return [
        "",
        f"All {count} terp-* distributions can move to {target} together, and the",
        "@terpjs/* packages move with them. Re-render FIRST — the template owns",
        "pyproject.toml and both npm manifests, so the re-render writes every pin",
        "itself, and it refuses to run on a tree with uncommitted changes:",
        "",
        "  1. Read what changed — only what you have not seen, Security first:",
        f"       uvx --from terp-cli=={target} terp guide changelog --since {current}",
        f"     (the {target} notes; the copy installed here ends at {current}).",
        "  2. Commit or discard what you have. A re-render on a dirty tree is refused,",
        "     and its own diff is much easier to review on its own.",
        "  3. copier update          (or the Studio's upgrade flow, which records the",
        "     answers file it needs). This rewrites EVERY file the template owns and",
        "     writes the terp-* and @terpjs/* pins for you. Its --pretend lists none of",
        "     that, so do not judge the update by a dry run: review what it did as its",
        "     own diff (git status, git diff) — that is why step 2 cleans the tree.",
        "  4. Resolve what it reports: conflict markers in the file, or a *.rej beside it",
        "     when it ran with --conflict rej. Two conflicts are structural, not bad luck,",
        "     because the template owns the file and your app also writes to it:",
        "       pyproject.toml            keep your dependencies, take the terp-* pins.",
        "       control_plane/operations.py  the capability folding is the template's;",
        "                                 your own operations belong in",
        "                                 control_plane/app_operations.py, which no",
        "                                 re-render touches (ADR 0130).",
        "  5. uv sync --refresh && npm --prefix frontend install",
        *suite_install(conformance),
        "     (once, now that the manifests are final — not before the re-render.)",
        *render,
        f"  {after}. uv run terp --version          (confirm the set agrees)",
        f"  {after + 1}. uv run terp verify --profile full",
        "",
        "  Running the dev stack in containers?",
        "  Rebuild it rather than reloading into it: the images bake the terp packages",
        "  in while the source is bind-mounted, so correct new code reloads against old",
        "  libraries and dies on an import nowhere near its cause. `terp docker dev`",
        "  rebuilds on a pyproject.toml change; a plain `docker compose up` does not,",
        "  and `terp verify` now refuses the skew either way. Coming from 0.29 or older,",
        "  a stack that is already up keeps its old node_modules volume where 0.30.0",
        "  declares a tmpfs. `terp docker dev` removes it before it starts; with plain",
        "  compose, run `up --force-recreate --renew-anon-volumes` once.",
        "",
        "A green gate proves the upgrade did not break this app. It cannot prove the",
        "release did not change something this app should adopt — step 1 is the only",
        "thing that answers that.",
    ]


def hand_pin_recipe(
    target: str,
    current: str,
    count: int,
    reason: str,
    *,
    generated: bool = False,
    conformance: bool = False,
) -> list[str]:
    """The upgrade for an app that cannot re-render: every pin by hand.

    The pins the template would have written have to be written here instead. Kept in
    full for exactly that case and printed nowhere else — an app the template can update
    is told to re-render, because doing both is what produced two needless installs.

    *reason* says which way the re-render is unavailable, because "no answers file" is
    only one of them and a recipe that names the wrong obstacle sends a reader to fix
    something that is not broken. A generated app renders after the sync, as above.
    """
    render = render_step(5) if generated else []
    after = 6 if generated else 5
    return [
        "",
        f"All {count} terp-* distributions can move to {target} together, and the",
        "@terpjs/* packages with them.",
        f"This app {reason};",
        "the pins have to be written by hand:",
        "",
        "  1. Read what changed — only what you have not seen, Security first:",
        f"       uvx --from terp-cli=={target} terp guide changelog --since {current}",
        f"     (the {target} notes; the copy installed here ends at {current}).",
        f"  2. Pin every terp-* dependency to =={target} in pyproject.toml",
        "     (including the dev group — a forgotten pin is a mixed install).",
        f"  3. Pin every @terpjs/* package to ^{target} in EVERY manifest that",
        "     declares one — frontend/package.json AND conformance/package.json",
        "     (a recipe that names only one is how the other goes stale).",
        "  4. uv sync --refresh && npm --prefix frontend install",
        *suite_install(conformance),
        *render,
        f"  {after}. uv run terp --version          (confirm the set agrees)",
        f"  {after + 1}. uv run terp verify --profile full",
        "",
        "A green gate proves the upgrade did not break this app. It cannot prove the",
        "release did not change something this app should adopt — step 1 is the only",
        "thing that answers that.",
    ]


__all__ = ["hand_pin_recipe", "render_step", "rerender_recipe", "suite_install"]
