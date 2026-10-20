"""A JSON Schema reader for exactly the keywords the deployment declaration's schema uses.

``deployment.json`` is read against the schema the Terp Standard publishes, and this
package ships a byte-for-byte mirror of it (ADR 0184 decision 8). Reading the
declaration *through* that mirror, rather than through a second hand-written copy of
its rules, is what keeps the two from saying different things: the words are the
schema's, and this module only applies them.

It is deliberately small. A general validator is a dependency this harness does not
carry, and its messages are written for schema authors. These are written for whoever
has to fix the file: each names the field, what is wrong with it, and what is allowed
there. A keyword applies by the instance's type, as JSON Schema specifies, and values
compare as JSON values: a boolean is never a number.

**An unknown keyword fails loudly.** :func:`check_schema` refuses a schema that uses a
keyword this module does not apply, so a later schema that adds a constraint cannot be
read as if the constraint were not there. A silently ignored ``maxLength`` would make a
hostile string read as a valid one.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

#: Keywords that carry no constraint. ``$defs`` holds named vocabularies a reader looks
#: up by name; it is never applied to an instance by itself.
ANNOTATIONS = frozenset({"$schema", "$id", "$comment", "$defs", "title", "description", "default"})

#: Every keyword :func:`validate` applies.
CONSTRAINTS = frozenset(
    {
        "type",
        "enum",
        "const",
        "pattern",
        "minLength",
        "maxLength",
        "minimum",
        "exclusiveMinimum",
        "minItems",
        "maxItems",
        "uniqueItems",
        "required",
        "properties",
        "patternProperties",
        "additionalProperties",
        "items",
        "dependentRequired",
        "if",
        "then",
        "else",
    }
)

_TYPE_WORDS = {
    "object": "an object",
    "array": "a list",
    "string": "a string",
    "integer": "a whole number",
    "number": "a number",
    "boolean": "true or false",
}

_CONTROL = re.compile(r"[\u0000-\u001f\u007f-\u009f]")


class UnsupportedSchemaError(ValueError):
    """The schema uses a keyword or a type this reader does not apply."""


@dataclass(frozen=True)
class Problem:
    """One reason an instance does not satisfy the schema.

    *path* is where (``units[0].command``; ``""`` for the document itself) and *detail*
    the sentence that follows it.
    """

    path: str
    detail: str


def _subschemas(schema: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for key in ("items", "if", "then", "else"):
        if isinstance(schema.get(key), dict):
            yield schema[key]
    for key in ("properties", "patternProperties"):
        yield from (value for value in schema.get(key, {}).values() if isinstance(value, dict))


def check_schema(schema: dict[str, Any]) -> None:
    """Refuse a schema that uses anything :func:`validate` would not apply."""
    unknown = sorted(set(schema) - ANNOTATIONS - CONSTRAINTS)
    if unknown:
        raise UnsupportedSchemaError(f"unsupported schema keyword(s): {', '.join(unknown)}")
    declared = schema.get("type")
    if declared is not None and declared not in _TYPE_WORDS:
        raise UnsupportedSchemaError(f"unsupported schema type {declared!r}")
    if not isinstance(schema.get("additionalProperties", False), bool):
        raise UnsupportedSchemaError("additionalProperties is read as true or false only")
    for child in _subschemas(schema):
        check_schema(child)


def _canonical(value: Any) -> Any:
    """JSON equality: a boolean is never a number, and 1 and 1.0 are one number."""
    if isinstance(value, bool):
        return ("boolean", value)
    if isinstance(value, int | float):
        return ("number", float(value))
    if isinstance(value, list):
        return ("array", tuple(_canonical(item) for item in value))
    if isinstance(value, dict):
        return ("object", tuple(sorted((key, _canonical(item)) for key, item in value.items())))
    return ("string", value)


def _is(value: Any, declared: str) -> bool:
    if declared == "object":
        return isinstance(value, dict)
    if declared == "array":
        return isinstance(value, list)
    if declared == "string":
        return isinstance(value, str)
    if declared == "boolean":
        return isinstance(value, bool)
    if isinstance(value, bool):
        return False
    if declared == "integer":
        return isinstance(value, int) or (isinstance(value, float) and value.is_integer())
    return isinstance(value, int | float)


def _describe(value: Any) -> str:
    for declared in ("boolean", "object", "array", "string"):
        if _is(value, declared):
            return _TYPE_WORDS[declared]
    return "null" if value is None else _TYPE_WORDS["number"]


def _show(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _join(path: str, key: str | int) -> str:
    if isinstance(key, int):
        return f"{path}[{key}]"
    return f"{path}.{key}" if path else key


def validate(instance: Any, schema: dict[str, Any], path: str = "") -> list[Problem]:
    """Every way *instance* fails *schema*, in document order."""
    declared = schema.get("type")
    if declared is not None and not _is(instance, declared):
        return [Problem(path, f"must be {_TYPE_WORDS[declared]}, not {_describe(instance)}")]
    canonical = _canonical(instance)
    if "enum" in schema and canonical not in {_canonical(value) for value in schema["enum"]}:
        allowed = ", ".join(str(value) for value in schema["enum"])
        return [Problem(path, f"is {_show(instance)} (allowed: {allowed})")]
    if "const" in schema and canonical != _canonical(schema["const"]):
        return [Problem(path, f"is {_show(instance)} (allowed: {_show(schema['const'])})")]
    if isinstance(instance, str):
        return _string_problems(instance, schema, path)
    if isinstance(instance, list):
        return _array_problems(instance, schema, path)
    if isinstance(instance, dict):
        return _object_problems(instance, schema, path)
    return _number_problems(instance, schema, path)


def _string_problems(value: str, schema: dict[str, Any], path: str) -> list[Problem]:
    if "minLength" in schema and len(value) < schema["minLength"]:
        return [Problem(path, f"is shorter than {schema['minLength']} character(s)")]
    if "maxLength" in schema and len(value) > schema["maxLength"]:
        return [Problem(path, f"is {len(value)} characters long (at most {schema['maxLength']})")]
    pattern = schema.get("pattern")
    if pattern is None or re.search(pattern, value):
        return []
    control = _CONTROL.search(value)
    if control is not None:
        return [
            Problem(
                path,
                f"carries a control character (U+{ord(control.group()):04X}), which no "
                "string in this file may (allowed: text without control characters)",
            )
        ]
    return [Problem(path, f"is {_show(value)}, which does not match {pattern}")]


def _number_problems(value: Any, schema: dict[str, Any], path: str) -> list[Problem]:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return []
    if "minimum" in schema and value < schema["minimum"]:
        return [Problem(path, f"is {_show(value)} (allowed: at least {schema['minimum']})")]
    if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
        return [
            Problem(path, f"is {_show(value)} (allowed: more than {schema['exclusiveMinimum']})")
        ]
    return []


def _array_problems(value: list[Any], schema: dict[str, Any], path: str) -> list[Problem]:
    if "minItems" in schema and len(value) < schema["minItems"]:
        return [Problem(path, f"has {len(value)} item(s) (allowed: at least {schema['minItems']})")]
    if "maxItems" in schema and len(value) > schema["maxItems"]:
        return [Problem(path, f"has {len(value)} items (allowed: at most {schema['maxItems']})")]
    if schema.get("uniqueItems"):
        seen: set[Any] = set()
        for item in value:
            canonical = _canonical(item)
            if canonical in seen:
                return [Problem(path, f"lists {_show(item)} more than once")]
            seen.add(canonical)
    items = schema.get("items")
    if not isinstance(items, dict):
        return []
    problems: list[Problem] = []
    for index, item in enumerate(value):
        problems.extend(validate(item, items, _join(path, index)))
    return problems


def _allowed_fields(schema: dict[str, Any]) -> str:
    fields = sorted(schema.get("properties", {}))
    patterns = list(schema.get("patternProperties", {}))
    if "^\\$" in patterns:
        patterns.remove("^\\$")
        fields.append("a $-prefixed annotation")
    fields.extend(f"a key matching {pattern}" for pattern in patterns)
    return ", ".join(fields) or "nothing"


def _object_problems(value: dict[str, Any], schema: dict[str, Any], path: str) -> list[Problem]:
    properties: dict[str, Any] = schema.get("properties", {})
    patterns: dict[str, Any] = schema.get("patternProperties", {})
    problems: list[Problem] = []
    for name in schema.get("required", ()):
        if name not in value:
            hint = properties.get(name, {})
            allowed = hint.get("enum", [hint["const"]] if "const" in hint else [])
            suffix = f" (allowed: {', '.join(str(v) for v in allowed)})" if allowed else ""
            problems.append(Problem(_join(path, name), f"is required{suffix}"))
    for key, item in value.items():
        child = _join(path, key)
        matched = [sub for pattern, sub in patterns.items() if re.search(pattern, key)]
        if key in properties:
            problems.extend(validate(item, properties[key], child))
        elif matched:
            for sub in matched:
                problems.extend(validate(item, sub, child))
        elif schema.get("additionalProperties") is False:
            where = path or "the declaration"
            problems.append(
                Problem(child, f"is not a field of {where} (allowed: {_allowed_fields(schema)})")
            )
    for key, needed in schema.get("dependentRequired", {}).items():
        for name in needed:
            if key in value and name not in value:
                problems.append(Problem(_join(path, name), f"is required beside {key}"))
    if "if" in schema:
        branch = "then" if not validate(value, schema["if"], path) else "else"
        if isinstance(schema.get(branch), dict):
            problems.extend(validate(value, schema[branch], path))
    return problems
