"""The scaffolding files a re-render leaves alone, and the build files the framework's
generator owns, as ``terp upgrade --check`` reports them.

Split out of ``version.py`` as they were, when that file (recorded in
``packages/backend/OVERSIZED.json``) needed a line for the design brief the template now
seeds; ``version.py`` imports both lists back, so ``version._APP_OWNED_SCAFFOLD_FILES``
still names what it always did.
"""

from __future__ import annotations

#: The scaffolding files copier seeds once and never overwrites — ``_skip_if_exists`` in
#: ``template/copier.yml``. Everything else the template owns *is* rewritten by a
#: re-render, and that is the half a reader actually needs: the report used to name three
#: template-owned files as though they were the list, so someone weighing whether a
#: re-render would deliver a fix to, say, the Compose file had no way to tell from it.
#:
#: Some are authored (``theme.css``) and some are app-generated (``routes.gen.d.ts``), so
#: what the report can honestly say about the set is not that it carries hand-written
#: content but that copier seeds it once and it is the app's afterwards.
#:
#: Duplicated here because the template does not ship inside this wheel, so the CLI cannot
#: read ``copier.yml`` at runtime. Held against it by
#: ``test_the_app_owned_scaffold_list_matches_copier`` — the same treatment the theme
#: bootstrap's three duplicated facts get, so this list cannot rot into a wrong answer.
_APP_OWNED_SCAFFOLD_FILES = (
    "control_plane/app_operations.py",
    "deployment.json",
    "environment.schema.json",
    "escape-hatch-budget.json",
    "frontend/DESIGN.md",
    "frontend/escape-hatch-budget.json",
    "frontend/layout-contract.json",
    "frontend/src/house-style.css",
    "frontend/src/routes.gen.d.ts",
    "frontend/src/theme.css",
    "workbench.json",
)


#: The production build files the framework's generator owns where deployment.json says
#: ``"build": "generated"`` (``terp.arch.deployment.generator.OWNED_PATHS``, ADR 0187).
_GENERATOR_OWNED_FILES = ("Dockerfile.prod", "frontend/Dockerfile.prod", "site/Dockerfile.prod", "conformance/Dockerfile.prod", "docker-compose.prod.yml")
