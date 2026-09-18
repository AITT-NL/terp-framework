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
from terp.arch.rules._support import ArchViolation, _rel

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


def _assignment_pairs(target: ast.expr, value: ast.expr) -> list[tuple[str, ast.expr]]:
    """``(name, value node)`` pairs for an assignment, through destructuring.

    A tuple/list target with a same-arity tuple/list value pairs positionally
    — ``user, password = "svc", "hunter2"`` checks ``password`` against
    ``"hunter2"`` — recursively, so nested destructuring keeps precise pairs.
    Any other shape pairs every extractable target name with the whole value
    (``(password, label) = "literal"`` still flags ``password``).
    """
    if (
        isinstance(target, ast.Tuple | ast.List)
        and isinstance(value, ast.Tuple | ast.List)
        and len(target.elts) == len(value.elts)
    ):
        return [
            pair
            for element, paired in zip(target.elts, value.elts, strict=True)
            for pair in _assignment_pairs(element, paired)
        ]
    return [(name, value) for name in _target_names(target)]


def _credential_shaped(name: str) -> bool:
    """Case-insensitive substring match for names likely to hold credentials."""
    lowered = name.lower()
    return any(part in lowered for part in _CREDENTIAL_NAME_PARTS)


def _literal_string(node: ast.expr) -> str | None:
    """Return the literal string value of *node*, or ``None`` for dynamic values."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


#: Name endings that say the value NAMES something rather than holds it, each paired
#: with the grammar that claim implies. A suffix alone is never enough -- ``TOKEN_ENV =
#: "sk-live-abc123"`` is still a credential -- so the value has to look like the thing
#: the suffix says it is. ``_KEY`` is deliberately absent: that IS the credential word.
#:
#: Each pattern earns its place by REFUSING a password, which is a sharper bar than
#: "looks plausible". A plain identifier pattern does not clear it: ``hunter2`` is a
#: valid identifier, a valid header name and a valid env-var name once upper-cased, so
#: an identifier-shaped exemption exempts exactly the passwords people actually write.
#: This repository's own suite caught that on the first attempt at this rule. So the
#: conventions do the discriminating instead -- an environment variable's name is
#: multi-word, an HTTP header's name is hyphenated, a path starts at a root -- and each
#: pattern requires the separator that convention implies.
_STRUCTURAL_SUFFIXES = {
    # An environment variable's name: UPPER_SNAKE, and more than one word.
    "env": re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$"),
    # A URL or filesystem path, which starts at a root or at the current directory.
    "path": re.compile(r"^[./][^\s]*$"),
    # An HTTP header's name, which is hyphenated.
    "header": re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+$"),
}

#: Suffixes whose value is only exempt when it SPELLS THE NAME ITSELF -- the same
#: reasoning as the self-naming enum member, generalised. ``CLIENT_SECRET_FIELD =
#: "client_secret"`` carries no secret material: the literal is the identifier's own
#: wire spelling. No grammar could stand in for this, because a field name and a
#: password are the same shape; only the equality is evidence.
_SELF_NAMING_SUFFIXES = frozenset({"field", "column", "param", "reference"})

#: A literal with a substitution slot is a wire FORMAT, not a credential: the part that
#: would be secret is the part that is not there. A real key pasted inside one is still
#: caught -- the literal-format scan below reads every string in the tree regardless of
#: what name it is bound to.
_TEMPLATE_RE = re.compile(r"\{[^{}]*\}|%\([A-Za-z_][A-Za-z0-9_]*\)[sdr]|%[sdr](?![A-Za-z])")


def _environment_key_names(tree: ast.AST) -> set[str]:
    """Names this module itself uses as an environment-variable key.

    ``TOKEN_ENV = "SOME_API_TOKEN"`` followed by ``os.environ[TOKEN_ENV]`` is the
    module stating, in code, that the literal is the NAME of a credential rather than
    one. That is the strongest evidence available without leaving the file, and it is
    evidence the rule already had in front of it.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        key: ast.expr | None = None
        if isinstance(node, ast.Subscript) and base_name(node.value) == "environ":
            key = node.slice
        elif isinstance(node, ast.Call) and node.args:
            func = node.func
            if isinstance(func, ast.Name) and func.id == "getenv":
                key = node.args[0]
            elif isinstance(func, ast.Attribute) and (
                func.attr == "getenv"
                or (func.attr == "get" and base_name(func.value) == "environ")
            ):
                key = node.args[0]
        if isinstance(key, ast.Name):
            names.add(key.id)
    return names


def _structurally_not_a_credential(name: str, literal: str, env_keys: set[str]) -> bool:
    """Three shapes a credential cannot take, however credential-shaped the name is.

    The matcher stays broad on purpose -- narrowing the name list would lose real
    findings -- so these say what the VALUE is instead. The reason to have them at all
    is that the escape-hatch budget is this platform's only friction metric and its only
    ratchet: once a reviewer learns that a marker for this rule is usually nothing, the
    one that is something gets the same glance, and a fail-closed control has quietly
    become decoration.
    """
    if name in env_keys:
        return True
    if _TEMPLATE_RE.search(literal):
        return True
    stem, _, suffix = name.rpartition("_")
    suffix = suffix.lower()
    grammar = _STRUCTURAL_SUFFIXES.get(suffix)
    if grammar is not None:
        return bool(grammar.fullmatch(literal))
    if suffix in _SELF_NAMING_SUFFIXES and stem:
        return literal.lower().replace("-", "_") == stem.lower()
    return False


_ENUM_BASES = frozenset(
    {"Enum", "StrEnum", "IntEnum", "IntFlag", "Flag", "ReprEnum", "TextChoices"}
)


def _self_naming_enum_member_lines(tree: ast.AST) -> set[int]:
    """Lines of enum members whose value is just the member's own name.

    ``SECRET_REFERENCE = "secret_reference"`` inside a ``StrEnum`` is vocabulary, not
    a credential: the literal *is* the member name, so it carries no secret material.
    Without this the rule pushed authors to spell the same vocabulary as ``auto()``
    purely to dodge the check — a workaround that hides the wire value.
    """
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if not any(base_name(base) in _ENUM_BASES for base in node.bases):
            continue
        for statement in node.body:
            targets = (
                statement.targets
                if isinstance(statement, ast.Assign)
                else [statement.target]
                if isinstance(statement, ast.AnnAssign)
                else []
            )
            value = getattr(statement, "value", None)
            literal = _literal_string(value) if value is not None else None
            if literal is None:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and literal.lower() == target.id.lower():
                    lines.add(statement.lineno)
    return lines


def check_no_hardcoded_credentials(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """App code does not hard-code credentials or recognizable secret tokens.

    A credential-shaped assignment to a non-empty string literal is almost always a
    secret that should come from sealed config / environment wiring, not source. The
    rule also rejects common high-confidence secret literal formats anywhere in the
    tree so leaked keys are caught even when assigned to a bland variable name.

    Scope is the **whole scanned root**, not ``modules/`` (ADR 0136). A secret is a
    leak wherever it is committed, and the places it most often lands — a
    composition root wiring a client, a sibling worker package, a conftest — are
    exactly the ones outside the module tree. ``tests/`` and ``migrations/`` are
    scanned for the same reason.

    Four shapes are exempt, and each says something about the VALUE rather than
    softening the name list -- narrowing the names would lose real findings:

    * an enum member whose literal is its own name (``SECRET_REFERENCE =
      "secret_reference"``) is vocabulary, carrying no secret material;
    * a name the module itself uses as an environment key (``TOKEN_ENV =
      "SOME_API_TOKEN"``, then ``os.environ[TOKEN_ENV]``) is the NAME of a
      credential, which the module states in code;
    * a ``_ENV`` / ``_PATH`` / ``_HEADER`` name whose value matches the grammar that
      suffix implies, where each grammar is chosen to REFUSE a password: an
      environment variable's name is multi-word, a header's name is hyphenated, a
      path starts at a root. ``TOKEN_ENV = "sk-live-abc123"`` is still a credential,
      and so is ``TOKEN_ENV = "HUNTER2"``;
    * a ``_FIELD`` / ``_COLUMN`` / ``_PARAM`` / ``_REFERENCE`` name whose value spells
      the name itself (``CLIENT_SECRET_FIELD = "client_secret"``) -- the enum case
      generalised. No grammar can serve here, because a field name and a password are
      the same shape; only the equality is evidence;
    * a literal carrying a substitution slot (``"Bearer {token}"``) is a wire
      FORMAT: the part that would be secret is the part that is not there.

    None of them weakens the literal-format scan, which reads every string in the
    tree regardless of the name it is bound to -- so a real key pasted into any of
    these shapes is still caught.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root, skip_dirs=_SECURITY_SKIP_DIRS):
        tree = parse(path)
        rel = _rel(path, root)
        vocabulary_lines = _self_naming_enum_member_lines(tree)
        env_keys = _environment_key_names(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign | ast.AnnAssign):
                if node.lineno in vocabulary_lines:
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if node.value is not None:
                    for target in targets:
                        for name, paired in _assignment_pairs(target, node.value):
                            literal = _literal_string(paired)
                            if (
                                literal
                                and _credential_shaped(name)
                                and not _structurally_not_a_credential(
                                    name, literal, env_keys
                                )
                            ):
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
