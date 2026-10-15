"""Local JSON Schema validation (Draft 2020-12): schemas are checked before
any provider call; outputs are validated locally afterwards."""

import pytest

from suvix.contracts import EvidenceRef
from suvix.errors import UnsupportedSchemaError
from suvix.evidence import validate_evidence_timestamps
from suvix.validation import validate_data, validate_schema

SCHEMA = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "timestamp_seconds": {"type": "number"},
                    "event_type": {"type": "string"},
                },
                "required": ["timestamp_seconds", "event_type"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["events"],
    "additionalProperties": False,
}


def test_valid_schema_passes():
    validate_schema(SCHEMA)  # must not raise


def test_empty_schema_is_valid_json_schema():
    validate_schema({})  # {} allows anything; still a valid schema


def test_invalid_schema_rejected_before_any_provider_call():
    with pytest.raises(UnsupportedSchemaError):
        validate_schema({"type": "not-a-real-type"})


def test_non_dict_schema_rejected():
    with pytest.raises(UnsupportedSchemaError):
        validate_schema(["type", "object"])


def test_valid_data_passes():
    report = validate_data({"events": [{"timestamp_seconds": 1.5,
                                        "event_type": "goal"}]}, SCHEMA)
    assert report.valid is True
    assert report.issues == []


def test_missing_required_field_detected():
    report = validate_data({"nope": []}, SCHEMA)
    assert report.valid is False
    assert any("events" in (i.field or "") or "events" in i.message
               for i in report.issues)


def test_wrong_type_detected_with_json_pointer_field():
    report = validate_data(
        {"events": [{"timestamp_seconds": "soon", "event_type": "goal"}]}, SCHEMA)
    assert report.valid is False
    assert any(i.field == "/events/0/timestamp_seconds" for i in report.issues)


def test_unexpected_field_detected_when_prohibited():
    report = validate_data(
        {"events": [], "surprise": 1}, SCHEMA)
    assert report.valid is False


def test_evidence_timestamps_must_be_finite_and_ordered():
    issues = validate_evidence_timestamps([
        EvidenceRef(timestamp_seconds=5.0),
        EvidenceRef(start_seconds=3.0, end_seconds=7.0),
    ])
    assert issues == []


def test_evidence_rejects_negative_timestamp():
    issues = validate_evidence_timestamps([EvidenceRef(timestamp_seconds=-1.0)])
    assert len(issues) == 1
    assert issues[0].code == "evidence_timestamp_invalid"
