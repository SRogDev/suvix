"""Local validation: JSON Schema checks run before any provider call
(schema validity) and after extraction (structural conformance).

Draft: 2020-12 via the ``jsonschema`` package. A provider's claim of
structured output never replaces this local validation.
"""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from suvix.contracts import ValidationIssue, ValidationReport
from suvix.errors import UnsupportedSchemaError

SCHEMA_DRAFT = "2020-12"


def validate_schema(schema: Any) -> None:
    """Reject invalid schemas with a clear error, before any provider call."""
    if not isinstance(schema, dict):
        raise UnsupportedSchemaError(
            f"JSON Schema must be a dict, got {type(schema).__name__}.",
            details={"received_type": type(schema).__name__},
        )
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise UnsupportedSchemaError(
            f"Invalid JSON Schema (draft {SCHEMA_DRAFT}): {exc.message}",
            details={"schema_error": exc.message},
        ) from exc


def validate_data(data: Any, schema: dict[str, Any]) -> ValidationReport:
    """Validate extracted data against the developer's schema, locally."""
    validator = Draft202012Validator(schema)
    issues = [
        ValidationIssue(
            code="schema_violation",
            message=error.message,
            field="/" + "/".join(str(p) for p in error.absolute_path)
            if error.absolute_path
            else "/",
        )
        for error in validator.iter_errors(data)
    ]
    return ValidationReport(valid=not issues, issues=issues)
