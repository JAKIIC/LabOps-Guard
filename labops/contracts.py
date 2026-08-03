"""Small deterministic validator for the JSON-Schema subset used by LabOps Guard.

The project stays standard-library-only. The schemas remain ordinary JSON Schema
documents, while this module enforces the subset required by the local CLI.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class ContractError(ValueError):
    pass


_TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "null": type(None),
}


def _validate(value: Any, schema: dict, path: str = "$") -> None:
    expected = schema.get("type")
    if expected is not None:
        names = expected if isinstance(expected, list) else [expected]
        types = tuple(_TYPE_MAP[name] for name in names)
        if not isinstance(value, types) or (isinstance(value, bool) and "boolean" not in names):
            raise ContractError(f"{path}: expected {names}, got {type(value).__name__}")
    if "enum" in schema and value not in schema["enum"]:
        raise ContractError(f"{path}: {value!r} is not an allowed value")
    if isinstance(value, dict):
        missing = [name for name in schema.get("required", []) if name not in value]
        if missing:
            raise ContractError(f"{path}: missing required fields: {', '.join(missing)}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(properties))
            if extra:
                raise ContractError(f"{path}: unexpected fields: {', '.join(extra)}")
        for name, child in properties.items():
            if name in value:
                _validate(value[name], child, f"{path}.{name}")
    if isinstance(value, list):
        if len(value) < int(schema.get("minItems", 0)):
            raise ContractError(f"{path}: too few items")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            raise ContractError(f"{path}: too many items")
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                _validate(item, schema["items"], f"{path}[{index}]")
    if isinstance(value, str) and "pattern" in schema and not re.search(schema["pattern"], value):
        raise ContractError(f"{path}: value does not match pattern")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise ContractError(f"{path}: below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise ContractError(f"{path}: above maximum")


def load_schema(name: str, project_root: str | Path | None = None) -> dict:
    root = Path(project_root) if project_root else Path(__file__).resolve().parent.parent
    return json.loads((root / "schemas" / name).read_text(encoding="utf-8"))


def validate_document(document: Any, schema_name: str, project_root: str | Path | None = None) -> None:
    _validate(document, load_schema(schema_name, project_root))

