"""Error hierarchy: every suvix error subclasses SuvixError; provider-side
failures subclass ProviderRequestError so callers can catch them as a group."""

import pytest

from suvix import errors

ALL_ERRORS = [
    "SuvixError",
    "InvalidInputError",
    "UnsupportedSchemaError",
    "UnsupportedMediaError",
    "UnsupportedStrategyError",
    "ProviderConfigError",
    "ProviderRequestError",
    "RateLimitError",
    "ProviderTimeoutError",
    "MalformedOutputError",
    "SchemaValidationError",
    "RecoveryExhaustedError",
    "MediaProcessingError",
    "MissingEvidenceError",
    "ExtractionCancelledError",
]


def test_every_error_subclasses_suvix_error():
    for name in ALL_ERRORS:
        cls = getattr(errors, name)
        assert issubclass(cls, errors.SuvixError), name
        assert issubclass(cls, Exception), name


def test_provider_failures_group_under_provider_request_error():
    assert issubclass(errors.RateLimitError, errors.ProviderRequestError)
    assert issubclass(errors.ProviderTimeoutError, errors.ProviderRequestError)


def test_base_carries_message_and_details():
    err = errors.ProviderRequestError("boom", details={"status": 500})
    assert str(err) == "boom"
    assert err.details == {"status": 500}


def test_details_default_to_empty_dict_and_never_none():
    assert errors.SuvixError("x").details == {}


def test_can_be_raised_and_caught_as_suvix_error():
    with pytest.raises(errors.SuvixError):
        raise errors.SchemaValidationError("bad data", details={"issues": 2})
