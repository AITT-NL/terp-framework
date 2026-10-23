"""Personal-data rules: a field named like personal data says whether it is (ADR 0190).

The build-time half of the personal-data declaration. ``terp.core.Personal`` is what the
log, the audit trail and events read; this rule is what makes the declaration hard to
forget. A model field whose name says it holds personal data -- an email address, a phone
number, a date of birth, a national identifier, a person's name, a home address -- is
either declared with ``Personal(...)`` or carries a justified opt-out saying why it is not
(an organisation's support address is not a person's). Either way the decision is in the
source, where a reviewer reads it.

The vocabulary is deliberately short: names that hold personal data in nearly every app
they appear in. A ``postcode`` or a bare ``address`` belongs to a company as often as to a
person, so it is not here, and a field outside the vocabulary is declared by hand.
"""

from __future__ import annotations

import ast
import pathlib
import re

from terp.arch._ast import base_name, iter_python_files, parse
from terp.arch.rules._support import ArchViolation, _is_table_model_class, _rel

# Matched against the whole field name, lower-cased, at a word boundary: ``contact_email``
# and ``customer_date_of_birth`` are in it; ``email_verified`` and ``phone_count`` are not,
# because their last word is not the personal noun.
_PERSONAL_NAME_RE = re.compile(
    r"(?:^|_)(?:"
    r"e_?mails?|email_address(?:es)?"  # an email address
    r"|phones?|phone_numbers?|telephone(?:_number)?|mobile_number"  # a phone number
    r"|date_of_birth|birth_?date|birthday|dob"  # a date of birth
    r"|national_id(?:_number)?|national_(?:identification|identity)_number"  # a national id
    r"|social_security_number|ssn|bsn|passport_number"
    r"|(?:first|last|full|given|family|middle)_name|surname"  # a person's name
    r"|(?:home|residential)_address"  # where a person lives
    r")$"
)

# A class is a model when its bases reach one of these, by name, through the scanned tree.
_MODEL_ROOTS = frozenset({"SQLModel", "BaseModel", "BaseTable", "BaseSchema", "BaseUpdateSchema"})

_DECLARATION = "Personal"


def is_personal_field_name(name: str) -> bool:
    """Whether a field called *name* is, by its name, personal data."""
    return _PERSONAL_NAME_RE.search(name.lower()) is not None


def _model_class_names(trees: list[ast.Module]) -> frozenset[str]:
    """Class names that are models, directly or through a model base defined in the tree."""
    bases_of: dict[str, set[str]] = {}
    tables: set[str] = set()
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases_of.setdefault(node.name, set()).update(
                    name for base in node.bases if (name := base_name(base)) is not None
                )
                if _is_table_model_class(node):
                    tables.add(node.name)
    models = set(_MODEL_ROOTS) | tables
    changed = True
    while changed:
        changed = False
        for name, bases in bases_of.items():
            if name not in models and bases & models:
                models.add(name)
                changed = True
    return frozenset(models - _MODEL_ROOTS)


def _declares_personal(statement: ast.AnnAssign) -> bool:
    """Whether the field is declared ``Personal(...)``, as its value or in ``Annotated``."""
    for part in (statement.value, statement.annotation):
        if part is not None and any(
            isinstance(node, ast.Call) and base_name(node.func) == _DECLARATION
            for node in ast.walk(part)
        ):
            return True
    return False


def check_personal_fields_are_declared(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """A model field named like personal data is declared ``Personal``, or says why not.

    The log, the audit trail and events withhold a field's value only where the field is
    declared personal: nothing else tells an email address from any other string. So a
    field whose *name* says it holds personal data -- ``email``, ``phone_number``,
    ``date_of_birth``, ``national_id``, ``last_name``, ``home_address`` and the rest of a
    short vocabulary -- is declared with ``terp.core.Personal(...)`` on every model that
    declares it, the table and each schema, because a schema that redeclares the field
    plainly has redeclared it as not personal. A field that only looks personal (an
    organisation's ``support_email``) carries the opt-out marker with the reason it is not.
    """
    root = pathlib.Path(app_root)
    parsed = [(_rel(path, root), parse(path)) for path in iter_python_files(root)]
    models = _model_class_names([tree for _, tree in parsed])
    violations: list[ArchViolation] = []
    for rel, tree in parsed:
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or node.name not in models:
                continue
            for statement in node.body:
                if (
                    isinstance(statement, ast.AnnAssign)
                    and isinstance(statement.target, ast.Name)
                    and is_personal_field_name(statement.target.id)
                    and not _declares_personal(statement)
                ):
                    field = statement.target.id
                    violations.append(
                        ArchViolation(
                            "personal_fields_are_declared",
                            rel,
                            statement.lineno,
                            f"{node.name}.{field}: a field named like personal data is not "
                            "declared personal, so the log, the audit trail and events "
                            "would carry its value; declare it with Personal(...) from "
                            "terp.core on this model and every schema that redeclares it, "
                            "or, if it holds no person's data, say why with "
                            "'# arch-allow-personal-fields-are-declared: <reason>'",
                        )
                    )
    return sorted(violations, key=lambda violation: (violation.path, violation.line))


__all__ = ["check_personal_fields_are_declared", "is_personal_field_name"]
