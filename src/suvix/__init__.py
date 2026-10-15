"""Suvix — schema-guided video data extraction."""

from suvix.api import Suvix
from suvix.contracts import (
    EvidenceRef,
    ExecutionMetadata,
    ExtractionResult,
    UsageReport,
    ValidationIssue,
    ValidationReport,
)
from suvix.errors import (
    ExtractionCancelledError,
    InvalidInputError,
    MalformedOutputError,
    MediaProcessingError,
    MissingEvidenceError,
    ProviderConfigError,
    ProviderRequestError,
    ProviderTimeoutError,
    RateLimitError,
    RecoveryExhaustedError,
    SchemaValidationError,
    SuvixError,
    UnsupportedMediaError,
    UnsupportedSchemaError,
    UnsupportedStrategyError,
)
from suvix.options import ExtractionOptions

__version__ = "0.1.0"

__all__ = [
    "Suvix",
    "ExtractionOptions",
    "ExtractionResult",
    "EvidenceRef",
    "ValidationReport",
    "ValidationIssue",
    "UsageReport",
    "ExecutionMetadata",
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
    "__version__",
]
