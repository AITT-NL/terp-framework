"""``terp verify --only deployment`` — does the deploy declaration tell the truth?

The rule is the one ``workbench.json`` lives by, pointed at the deployment profile:
*did you tell the truth about yourself*, never *are you deployed the approved way*
(ADR 0184 decision 5). Red is exactly three things:

* the file **cannot be read** by this toolchain (``deployment_declaration_is_readable``);
* **rule 1's boundary**: a field read by role, under a role nothing looks up;
* **rule 2**: a fact the declaration states that the profile or the app contradicts.
  From the files (``deployment_declaration_tells_the_truth``): a unit that is not a
  service of the resolved profile, a restated ``command`` or ``dependsOn`` that
  differs, an ``env`` name the profile never passes, an image off the datastore table
  or not built from the checkout, a volume that backs up nothing, ``externalDatabase``
  beside a profile that still runs a database. From the app
  (:mod:`terp.cli.deployment_app`): a migration label nobody owns, and a health path
  the API does not serve.

Both file rules are ``terp.arch`` rules, so ``terp check`` holds an app to them as
well; this check adds the app part, which needs the composed app, and the notes.

**Never** red: no file at all; ``unmanaged``; a service nobody declared; no frontend;
three APIs; a role nobody has heard of that carries nothing read by role; a stateful
unit with no backup; a schedule with no scheduler; ``instances: "many"``; an installed
migration label no unit claims; any topology nobody predicted.
"""

from __future__ import annotations

import pathlib

from terp.arch.deployment import (
    DEPLOYMENT_FILE,
    Declaration,
    Finding,
    Unmanaged,
    published_table,
    readable,
    resolve_profile,
)
from terp.arch.deployment.profile import truth_findings


def _render(findings: list[Finding], notes: tuple[str, ...], *, unreadable: bool) -> str:
    lines = (
        [f"{DEPLOYMENT_FILE} cannot be read by this toolchain.", ""]
        if unreadable
        else [
            "The deployment this app declares does not match the one it has.",
            "",
            "Only what deployment.json CLAIMS is checked -- a service it does not name is",
            "not its business, and a topology nobody predicted is fine. Correct the",
            'declaration, or set {"unmanaged": true, "reason": "..."} if no tool can',
            "drive this app's deploy.",
            "",
        ]
    )
    for finding in findings:
        lines.append(f"- {finding.message}")
        if finding.remedy:
            lines.append(f"  {finding.remedy}")
    if notes:
        lines.extend(["", "Also noted (never red):", *(f"  {note}" for note in notes)])
    return "\n".join(lines)


def run_deployment_check(project_root: pathlib.Path) -> tuple[int, str]:
    """The ``deployment`` verify runner: ``(exit_code, output)``.

    A no-op success for an app with no declaration: upgrading the toolchain must never
    turn an app's gate red over a file it has not adopted.
    """
    from terp.cli.deployment_app import audit_app
    from terp.cli.verify import NOTE_PREFIX

    table = published_table()
    declared, findings = readable(project_root, table)
    if findings:
        return 1, _render(findings, (), unreadable=True)
    if declared is None:
        return 0, f"no {DEPLOYMENT_FILE} - deployment not declared"
    if isinstance(declared, Unmanaged):
        return 0, (
            f"{DEPLOYMENT_FILE} declares this app unmanaged: {declared.reason}\n"
            "A deploy tool will not drive it, and says so with that reason."
        )
    assert isinstance(declared, Declaration)
    findings = truth_findings(project_root, declared, table)
    profile, unresolved = resolve_profile(project_root, declared)
    notes: tuple[str, ...] = ()
    if not unresolved:
        report = audit_app(declared, profile, project_root, table)
        findings = [*findings, *report.findings]
        notes = report.notes
    if findings:
        return 1, _render(findings, notes, unreadable=False)
    summary = (
        f"{DEPLOYMENT_FILE}: {len(declared.units)} declared unit(s) match "
        f"{' + '.join(declared.profile_files)} (build: {declared.build})"
    )
    if not notes:
        return 0, summary
    return 0, NOTE_PREFIX + summary + "".join(f"\n  {note}" for note in notes)
