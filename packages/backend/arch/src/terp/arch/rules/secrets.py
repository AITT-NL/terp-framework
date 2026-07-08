"""Secrets rule: sealed config stays masked in app code — no ad-hoc decrypt.

The design's §5.4 control: ``decrypt_config`` may run from **exactly one**
allowlisted call site; every other surface renders ``mask_config``. This rule is
the build-time layer — it flags any ``decrypt_config(...)`` call in scanned app
code, so the one sanctioned site is a justified, budgeted ``# arch-allow-*``
opt-out (greppable, ratcheted). The runtime half is the fail-closed call-site
allowlist inside ``terp.core.secrets.decrypt_config`` itself.
"""

from __future__ import annotations

import ast
import pathlib
import re

from terp.arch._ast import _SECURITY_SKIP_DIRS, base_name, iter_python_files, parse
from terp.arch.rules._support import ArchViolation, _module_under, _rel

_CREDENTIAL_NAME_PARTS = (
    "password",
    "passwd",
    "secret",
    "api_key",
    "apikey",
    "token",
    "private_key",
    "access_key",
    "auth_key",
    "client_secret",
)
_SECRET_LITERAL_RE = re.compile(
    r"AKIA[0-9A-Z]{16}"
    r"|ghp_[A-Za-z0-9]{36}"
    r"|github_pat_[A-Za-z0-9_]{22,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)


def _target_names(target: ast.expr) -> list[str]:
    """Assignment target names whose spelling can be checked for credential words."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Attribute):
        return [target.attr]
    if isinstance(target, ast.Tuple | ast.List):
        return [name for element in target.elts for name in _target_names(element)]
    return []


def _credential_shaped(name: str) -> bool:
    """Case-insensitive substring match for names likely to hold credentials."""
    lowered = name.lower()
    return any(part in lowered for part in _CREDENTIAL_NAME_PARTS)


def _literal_string(node: ast.expr) -> str | None:
    """Return the literal string value of *node*, or ``None`` for dynamic values."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def check_no_hardcoded_credentials(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """App modules do not hard-code credentials or recognizable secret tokens.

    A credential-shaped assignment to a non-empty string literal is almost always a
    secret that should come from sealed config / environment wiring, not source. The
    rule also rejects common high-confidence secret literal formats anywhere in a
    module so leaked keys are caught even when assigned to a bland variable name.
    As a security rule this also scans ``tests/`` and ``migrations/`` dirs inside a
    module — a real secret is a leak wherever it is committed.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root, skip_dirs=_SECURITY_SKIP_DIRS):
        if _module_under(path, package) is None:
            continue
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign | ast.AnnAssign):
                value = _literal_string(node.value)
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if value:
                    for name in [target_name for target in targets for target_name in _target_names(target)]:
                        if _credential_shaped(name):
                            violations.append(
                                ArchViolation(
                                    "no_hardcoded_credentials",
                                    rel,
                                    node.lineno,
                                    f"assignment to credential-shaped name {name!r} uses a "
                                    "non-empty string literal; load credentials from sealed "
                                    "config/environment wiring instead",
                                )
                            )
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if _SECRET_LITERAL_RE.search(node.value):
                    violations.append(
                        ArchViolation(
                            "no_hardcoded_credentials",
                            rel,
                            node.lineno,
                            "source contains a literal matching a common secret/token format; "
                            "remove it and load the value from sealed config/environment wiring",
                        )
                    )
    return violations



def check_no_adhoc_config_decrypt(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Sealed config is never decrypted ad hoc; one budgeted call site only.

    A sealed configuration value (``enc:v1:...``) stays opaque in app code: a
    module renders ``mask_config`` and never calls ``decrypt_config``. The single
    sanctioned decrypt site (design §5.4) carries a justified
    ``# arch-allow-no-adhoc-config-decrypt`` marker counted against the app's
    escape-hatch budget. Its runtime half is
    :func:`terp.core.secrets.decrypt_config`, which fails closed unless called
    from the one site registered via ``register_decrypt_call_site``.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and base_name(node.func) == "decrypt_config":
                violations.append(
                    ArchViolation(
                        "no_adhoc_config_decrypt",
                        rel,
                        node.lineno,
                        "decrypt_config may run from exactly one allowlisted call "
                        "site; render mask_config here, or justify the single "
                        "decrypt site with a budgeted arch-allow marker",
                    )
                )
    return violations
