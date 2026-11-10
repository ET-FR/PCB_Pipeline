"""JSON Schema loading and validation."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"


@lru_cache
def _validator(name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def validate(name: str, doc: dict) -> list[str]:
    """Return a list of human-readable errors (empty if valid)."""
    errors = sorted(_validator(name).iter_errors(doc), key=lambda e: list(e.path))
    return [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors]
