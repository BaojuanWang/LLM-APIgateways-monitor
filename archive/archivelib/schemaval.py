"""JSON Schema validation for the subsystem's own artifacts.

Optional by design: ``jsonschema`` may not be installed on a machine that only
needs to *read* an old corpus, and a missing linter must never block access to
evidence. When the package is absent, ``validate_document`` reports that it was
skipped instead of failing.
"""

from __future__ import annotations

from pathlib import Path

from .canonical import read_json

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"

SCHEMA_FILES = {
    "site": "site.schema.json",
    "capture": "capture.schema.json",
    "tombstone": "tombstone.schema.json",
    "public_capture_index": "public_capture_index.schema.json",
}


def schema_path(name: str) -> Path:
    if name not in SCHEMA_FILES:
        raise KeyError(f"unknown schema {name!r}; known: {sorted(SCHEMA_FILES)}")
    return SCHEMA_DIR / SCHEMA_FILES[name]


def load_schema(name: str) -> dict:
    return read_json(schema_path(name))


def validate_document(document: dict, schema_name: str) -> dict:
    """Validate ``document``; returns a report, never raises on invalidity."""
    try:
        import jsonschema
    except ImportError:
        return {"schema": schema_name, "skipped": True, "reason": "jsonschema not installed", "valid": None, "errors": []}

    schema = load_schema(schema_name)
    validator = jsonschema.Draft202012Validator(schema)
    errors = [
        {"path": "/".join(str(p) for p in err.absolute_path) or "<root>", "message": err.message}
        for err in sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path))
    ]
    return {"schema": schema_name, "skipped": False, "valid": not errors, "errors": errors[:50]}
