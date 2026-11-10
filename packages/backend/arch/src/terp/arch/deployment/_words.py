"""The words a deployment-declaration refusal says what a field allows in.

terp-spec's ``deployment-declaration.fixtures.json`` names, for every violation case, the
field a reader refuses and the values that field allows, and every reader's message
carries both: the framework's check, ``terp promote`` and terp-runner say one refusal
in one set of words. The lists (keys, words, values) come from the schema and the
tables; only the sentences below are written by hand, one per field a pattern or a
type constrains, as a person reads the constraint.

:func:`say` turns one :class:`~terp.arch.deployment._jsonschema.Problem` into such a
message; the reader's own refusals take their sentences from here too.
"""

from __future__ import annotations

import difflib
import json
import re
from typing import Any

from terp.arch.deployment import _jsonschema
from terp.arch.deployment._jsonschema import Problem

#: The document itself, in a message.
DOCUMENT = "deployment.json"

#: The forms a field's pattern or type enforces, said as a person reads them.
FORMS: dict[str, str] = {
    "reason": "a sentence saying why a tool cannot drive this deploy",
    "compose": "an object naming the deployment profile's file",
    "compose.file": "a path relative to the project root, with forward slashes",
    "compose.overrides": "a list of paths relative to the project root, with forward slashes",
    "compose.overrides[]": "a path relative to the project root, with forward slashes",
    "units": "at least one unit",
    "units[]": "a unit: an object with an id and a role",
    "units[].id": "a unit id: a letter or digit, then letters, digits, '.', '_' or '-'",
    "units[].role": "a role: a lower-case letter, then lower-case letters, digits or hyphens",
    "units[].command": "an argument list of strings, never a shell string",
    "units[].command[]": "an argument: text without control characters",
    "units[].healthPath": "a path that starts with / and holds only URL path characters",
    "units[].livenessPath": "a path that starts with / and holds only URL path characters",
    "units[].migrations": "a list of migration history labels",
    "units[].migrations[]": "a migration history's label: a letter, digit or '_', then "
    "letters, digits, '_', '.' or '-'",
    "units[].env": "a list of variable names",
    "units[].env[]": "an upper-case variable name, as the variable manifest declares one",
    "units[].dependsOn": "a list of declared unit ids",
    "units[].dependsOn[]": "a declared unit's id",
    "units[].size": "a size name: a lower-case letter, then lower-case letters, digits or hyphens",
    "units[].stateful": "true or false",
    "units[].backup": "a policy with every and keep - client is valid only on externalDatabase",
    "units[].backup.every": "an ISO 8601 duration, such as P1D or PT6H",
    "units[].backup.keep": "an ISO 8601 duration, such as P30D",
    "volumes": "a list of named volumes",
    "volumes[]": "a volume: an object with an id",
    "volumes[].id": "a named volume's id: a letter or digit, then letters, digits, '.', '_' or '-'",
    "volumes[].backup": "a policy with every and keep - client is valid only on externalDatabase",
    "volumes[].backup.every": "an ISO 8601 duration, such as P1D or PT6H",
    "volumes[].backup.keep": "an ISO 8601 duration, such as P30D",
    "volumes[].mount": "a mount: in the generated state the generator renders where each "
    "volume goes",
    "volumes[].mount.units": "a list of declared unit ids",
    "volumes[].mount.units[]": "a declared unit's id",
    "generator": "an object of the generator's words",
    "generator.systemPackages": "a list of system package names",
    "generator.systemPackages[]": "a package name: lower-case letters, digits, + . and -, "
    "beginning with a letter or a digit",
    "generator.recipes": "an object naming the recipe each web unit's image is built from",
    "sizes": "an object of named sizes",
    "sizes.*": "a size: an object with cpu and memoryMiB",
    "sizes.*.cpu": "a number of cores above 0",
    "sizes.*.memoryMiB": "a whole number of mebibytes, at least 1",
    "externalDatabase": "an object whose backup is client",
    "externalDatabase.backup": "client",
    "rollback": "an object with a strategy",
}

#: What a key-holding object is called, for the message about a key it does not have.
HOLDERS = {
    "": "the top-level keys",
    "compose": "the keys of compose",
    "units[]": "a unit's keys",
    "units[].backup": "a backup policy's keys",
    "volumes[]": "a volume's keys",
    "volumes[].backup": "a backup policy's keys",
    "volumes[].mount": "a mount's keys",
    "generator": "the keys of generator",
    "sizes.*": "a size's keys",
    "externalDatabase": "the keys of externalDatabase",
    "rollback": "the keys of rollback",
}

#: A key a person reaches for, and why the vocabulary has none.
NO_SUCH_KEY = {
    ("units[]", "image"): "there is no image key: name a datastore by kind and version, or "
    "build the unit from the checkout",
    ("", "environments"): "an environment is the deploying tool's record, not this file",
    ("", "environment"): "an environment is the deploying tool's record, not this file",
}

#: A mount path's two forms: outside var/, and a hidden segment.
MOUNT_OUTSIDE = "a path inside var/, relative to where the image runs the app, such as var/files"
MOUNT_HIDDEN = "a path inside var/ with no segment that begins with a dot"
GENERATOR_BESIDE_OWN = "nothing beside build own - generator is valid only beside build generated"
STATEFUL = "true - a backup policy sits only on a unit declared stateful"


def or_join(values: list[Any] | tuple[Any, ...]) -> str:
    """``a, b or c``, each value as the file writes it."""
    words = [value if isinstance(value, str) else json.dumps(value) for value in values]
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " or " + words[-1]


def json_kind(value: Any) -> str:
    """A value's JSON kind, as a person names it: an array, not a list."""
    if isinstance(value, list):
        return "an array"
    if isinstance(value, dict):
        return "an object"
    if isinstance(value, bool):
        return "a boolean"
    if isinstance(value, str):
        return "a string"
    return "null" if value is None else "a number"


_STEP = re.compile(r'\[(\d+)\]|\[("(?:[^"\\]|\\.)*")\]|\.?([^.\[]+)')


def steps(path: str) -> list[str | int]:
    """``units[0].backup.every`` as ``["units", 0, "backup", "every"]``."""
    found: list[str | int] = []
    for index, quoted, plain in _STEP.findall(path):
        found.append(int(index) if index else json.loads(quoted) if quoted else plain)
    return found


def shape(path: str) -> str:
    """The field's place in the vocabulary: ``units[].command[]``, ``sizes.*.cpu``."""
    out: list[str] = []
    parts = steps(path)
    for index, part in enumerate(parts):
        if isinstance(part, int):
            out[-1] = out[-1] + "[]"
        elif index == 1 and parts[0] == "sizes":
            out.append("*")
        else:
            out.append(str(part))
    return ".".join(out)


def lookup(document: Any, path: str) -> Any:
    """The value at *path* in *document*, or ``None``."""
    node = document
    for part in steps(path):
        if isinstance(part, int) and isinstance(node, list) and part < len(node):
            node = node[part]
        elif isinstance(part, str) and isinstance(node, dict):
            node = node.get(part)
        else:
            return None
    return node


def _parent(path: str) -> str:
    match = re.search(r'(\[\d+\]|\["(?:[^"\\]|\\.)*"\]|\.?[^.\[]+)$', path)
    return path[: match.start()] if match else ""


def policy_key_paths(node: Any, keys: tuple[str, ...], path: str = "") -> list[str]:
    """Where a deploy-policy key (one of *keys*) appears as a key, at any depth."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            # The join every other path uses: an odd key is written escaped and cut, and a
            # dot inside one is no deeper step.
            child = _jsonschema._join(path, str(key))
            if key in keys:
                found.append(child)
            found.extend(policy_key_paths(value, keys, child))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(policy_key_paths(value, keys, f"{path}[{index}]"))
    return found


def version_allowed(kind: Any, kinds: dict[str, tuple[str, ...]]) -> str:
    """The versions the datastore table carries for *kind*."""
    versions = kinds.get(kind, ()) if isinstance(kind, str) else ()
    if not versions:
        return "the datastore version, declared with its kind"
    return f"the datastore version, declared with its kind: {or_join(sorted(versions))} for {kind}"


def web_units(document: Any) -> str:
    units = document.get("units") if isinstance(document, dict) else None
    ids = sorted(
        unit["id"]
        for unit in (units if isinstance(units, list) else [])
        if isinstance(unit, dict) and unit.get("role") == "web" and isinstance(unit.get("id"), str)
    )
    # Read before the schema has refused a bad id, so each is written as a path writes a key.
    return ", ".join(_jsonschema.name(ident, _jsonschema._PLAIN_KEY) for ident in ids) or "none"


def _allowed(path: str, problem: Problem, document: Any, kinds: dict[str, tuple[str, ...]]) -> str:
    """What the field at *path* allows, for a type, required or form refusal."""
    where = shape(path)
    if problem.keyword == "required" and problem.values:
        return or_join(problem.values)
    if where == "units[].kind":
        return f"a datastore kind of the table: {or_join(sorted(kinds)) or 'none'}"
    if where == "units[].version":
        return version_allowed(lookup(document, f"{_parent(path)}.kind"), kinds)
    if where.startswith("$") or where.rsplit(".", 1)[-1].startswith("$"):
        return "an annotation: text without control characters"
    return FORMS.get(where, "the value the vocabulary gives this field")


def unknown_key(problem: Problem, document: Any) -> str:
    """A key the object it sits in does not have, with every key that object does."""
    parent = _parent(problem.path)
    key = steps(problem.path)[-1]
    holder_shape = shape(parent)
    here = f"{problem.path} is not a field of {parent or 'the declaration'}"
    known = list(problem.values)
    if not parent and lookup(document, "build") != "generated":
        known = [name for name in known if name != "generator"]
    if holder_shape == "sizes":
        return f"{problem.path} is not a size name (allowed: {FORMS['units[].size']})"
    if holder_shape == "generator.recipes":
        return f"{here} (allowed: a declared web unit's id: {web_units(document)})"
    holder = HOLDERS.get(holder_shape, "the keys here")
    reason = NO_SUCH_KEY.get((holder_shape, str(key)))
    close = difflib.get_close_matches(str(key), known, n=1, cutoff=0.8)
    if reason is not None:
        return f"{here} (allowed: {holder}: {', '.join(known)} - {reason})"
    if close:
        return f"{here} (allowed: {holder}, among them {close[0]}: {', '.join(known)})"
    return f"{here} (allowed: {holder}: {', '.join(known)})"


def say(problem: Problem, document: Any, kinds: dict[str, tuple[str, ...]]) -> str:
    """One schema refusal, as a message that names its field and what that field allows.

    *kinds* is the datastore table: each kind and the versions it carries.
    """
    path = problem.path
    where = path or DOCUMENT
    form = shape(path)
    keyword, detail = problem.keyword, problem.detail
    if keyword == "additionalProperties":
        return unknown_key(problem, document)
    if keyword == "required":
        what = "is required when units are declared" if form == "build" else "is required"
        return f"{where} {what} (allowed: {_allowed(path, problem, document, kinds)})"
    if keyword == "dependentRequired":
        need = steps(path)[-1]
        if need == "version":
            allowed = version_allowed(lookup(document, f"{_parent(path)}.kind"), kinds)
        elif need == "kind":
            allowed = f"the datastore kind, declared with its version: {or_join(sorted(kinds)) or 'none'}"
        else:
            allowed = STATEFUL
        return f"{where} is required beside {problem.values[0]} (allowed: {allowed})"
    if keyword in ("pattern", "minLength"):
        if form == "reason":
            return f"{where} is blank (allowed: a sentence that is not blank)"
        if form == "volumes[].mount.path" and keyword == "pattern":
            value = str(lookup(document, path))
            segments = value.split("/")
            hidden = segments[0] == "var" and any(part.startswith(".") for part in segments)
            return f"{where} {problem.shown} (allowed: {MOUNT_HIDDEN if hidden else MOUNT_OUTSIDE})"
        shown = problem.shown if keyword == "pattern" else detail
        return f"{where} {shown} (allowed: {_allowed(path, problem, document, kinds)})"
    if keyword == "maxLength":
        length = detail.split(" (")[0]
        return f"{where} {length} (allowed: at most {problem.values[0]} characters)"
    if keyword == "maxItems":
        return f"{where} {detail.split(' (')[0]} (allowed: at most {problem.values[0]} entries)"
    if keyword == "uniqueItems":
        return f"{where} {detail} (allowed: each entry once)"
    if keyword in ("minItems", "minimum", "exclusiveMinimum") and form in FORMS:
        return f"{where} {detail.split(' (')[0]} (allowed: {FORMS[form]})"
    if keyword == "type":
        return f"{where} {detail} (allowed: {_allowed(path, problem, document, kinds)})"
    if keyword == "enum":
        return f"{where} {problem.shown} (allowed: {or_join(problem.values)})"
    if keyword == "const":
        # ``unmanaged`` never reaches here: any value but true is the reader's own refusal.
        allowed = STATEFUL if form == "units[].stateful" else or_join(problem.values)
        return f"{where} {problem.shown} (allowed: {allowed})"
    return f"{where} {detail}"
