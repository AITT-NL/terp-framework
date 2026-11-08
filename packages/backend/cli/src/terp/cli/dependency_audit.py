"""``dependency-audit-npm`` — every npm lock the release jobs read, audited where it lies.

The npm half of the dependency-audit assurance lane. A static site's image is built from
``site/package-lock.json`` beside the SPA's ``frontend/package-lock.json`` (ADR 0198), and the
release jobs read both, so the audit reads both: one ``npm audit --audit-level=high`` per lock of
:data:`terp.cli.release._locks.NPM_LOCKS`, and per lock any other web image is built from by the
release plan's own rule (:func:`terp.cli.release._plan.web_npm_locks`), the locks the locks check
holds too. A lock is audited where its ``package.json`` exists, as ``terp verify --only locks`` decides:
a ``site/`` that holds pages or Markdown and no ``package.json`` is no npm workspace, and has
nothing to audit. Each audit runs as a manifest command does, through the npm seam
(:func:`terp.cli.verify._run_subprocess`), so an unusable ``node_modules`` names its fix; and a
workspace missing while a manifest elsewhere depends on the package that marks it stays the red
every npm check gives it. The check is not applicable only when every lock is (ADR 0202).
"""

from __future__ import annotations

import pathlib

from terp.cli.release._locks import NPM_LOCKS, NPM_SCOPE, npm_manifest, npm_workspace

#: The check's id, under which each audit it runs reports.
CHECK_ID = "dependency-audit-npm"


def run_dependency_audit_npm(root: pathlib.Path) -> tuple[int, str]:
    """The ``dependency-audit-npm`` verify runner: ``(exit_code, output)``.

    The first line is the verdict, each lock by name, and says not applicable only when every
    lock did; a missing workspace's note follows it, and the failing audits' own output comes
    last, where the envelope's tail keeps it.
    """
    from terp.arch.deployment import published_table
    from terp.cli.release._plan import web_npm_locks
    from terp.cli.verify import NOT_APPLICABLE, VerifyCheck, _applicable, _missing_workspace, _run_subprocess

    planned = [npm_lock for npm_lock in web_npm_locks(root, published_table()) if npm_lock not in NPM_LOCKS]
    answers = []
    for npm_lock in (*NPM_LOCKS, *planned):
        if not (root / npm_manifest(npm_lock)).is_file():
            kept = _missing_workspace(root, npm_workspace(npm_lock), CHECK_ID)
            if kept is not None and kept[0] != 0:  # the workspace kept somewhere it is not read
                answers.append((npm_lock, kept[0], kept[1], True))
            else:
                answers.append((npm_lock, 0, f"no {npm_manifest(npm_lock)} - {CHECK_ID} {NOT_APPLICABLE}", False))
            continue
        audit = VerifyCheck(
            id=CHECK_ID,
            category="architecture",
            command=f"npm --prefix {npm_workspace(npm_lock)} audit --audit-level=high",
        )
        code, output = _run_subprocess(audit, root)
        answers.append((npm_lock, code, output.strip(), _applicable(code == 0, output)))
    judged = [answer for answer in answers if answer[3]]
    if not judged:
        missing = " or ".join(npm_manifest(npm_lock) for npm_lock in (*NPM_LOCKS, *planned))
        return 0, f"no {missing} - {CHECK_ID} {NOT_APPLICABLE}"
    verdicts = ", ".join(
        f"{npm_lock} {'passed' if code == 0 else f'FAILED (exit {code})'}"
        for npm_lock, code, _output, _judged in judged
    )
    lines = [f"npm audit of every npm lock the release reads: {verdicts}"]
    lines += [output for _lock, _code, output, applies in answers if not applies]
    for npm_lock, code, output, _judged in sorted(judged, key=lambda answer: answer[1] != 0):
        lines += [f"--- {npm_lock}", output]
    return next((code for _lock, code, _output, _judged in judged if code != 0), 0), "\n".join(lines)


__all__ = ["CHECK_ID", "NPM_SCOPE", "run_dependency_audit_npm"]
