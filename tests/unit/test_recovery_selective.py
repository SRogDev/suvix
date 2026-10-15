"""Selective recovery improvements (Milestone 6).

Covers the new ``classify_issues`` helper, the warnings-only recovery gate
(warnings must not burn the provider-call budget), and the improved repair
prompt: grouped by field, capped, and explicit about never fabricating data.
"""

from __future__ import annotations

from suvix.contracts import ValidationIssue, ValidationReport
from suvix.recovery import (
    build_repair_instructions,
    classify_issues,
    is_recoverable,
)


def _error(code="schema_violation", field="/", message="bad"):
    return ValidationIssue(code=code, message=message, field=field)


def _warning(code="evidence_duplicate", field="evidence[1]", message="dup"):
    return ValidationIssue(code=code, message=message, field=field, severity="warning")


def test_warnings_only_report_is_not_recoverable():
    report = ValidationReport(valid=False, issues=[_warning(), _warning("w2")])
    assert is_recoverable({"data": 1}, report) is False


def test_mixed_severity_report_is_recoverable():
    report = ValidationReport(valid=False, issues=[_warning(), _error()])
    assert is_recoverable({"data": 1}, report) is True


def test_errors_only_report_is_recoverable():
    report = ValidationReport(valid=False, issues=[_error()])
    assert is_recoverable({"data": 1}, report) is True


def test_classify_issues_groups_by_code():
    report = ValidationReport(
        valid=False,
        issues=[_error("a"), _error("b"), _error("a"), _warning("b")],
    )
    grouped = classify_issues(report)
    assert set(grouped) == {"a", "b"}
    assert len(grouped["a"]) == 2
    assert len(grouped["b"]) == 2


def test_classify_issues_empty_report():
    assert classify_issues(ValidationReport(valid=True)) == {}


def test_repair_instructions_group_issues_by_field():
    report = ValidationReport(
        valid=False,
        issues=[_error(field="/events/0"), _error(field="/events/1")],
    )
    text = build_repair_instructions(report)
    assert "/events/0" in text
    assert "/events/1" in text


def test_repair_instructions_forbid_fabrication():
    report = ValidationReport(valid=False, issues=[_error()])
    text = build_repair_instructions(report)
    assert (
        "Do not invent values for information not visible; "
        "omit fields the schema allows omitting rather than fabricating."
    ) in text


def test_repair_instructions_still_capped():
    report = ValidationReport(
        valid=False, issues=[_error(message=f"issue {i}") for i in range(12)]
    )
    text = build_repair_instructions(report)  # default cap of 10
    assert "issue 11" not in text
    assert "... and 2 more." in text
