"""Suvix error contract.

Every error raised by the library subclasses :class:`SuvixError` so callers
can catch the whole family. Provider-side failures (request errors, rate
limits, timeouts) additionally subclass :class:`ProviderRequestError`.

``details`` carries debugging context (field names, counts, provider codes).
Adapters must never put credentials or video content in ``details``.
"""

from __future__ import annotations

from typing import Any


class SuvixError(Exception):
    """Base class for all Suvix errors."""

    def __init__(self, message: str = "", *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details: dict[str, Any] = details if details is not None else {}


class InvalidInputError(SuvixError):
    """The caller's request is malformed (bad video reference, empty instructions)."""


class UnsupportedSchemaError(SuvixError):
    """The provided JSON Schema is invalid or uses unsupported constructs."""


class UnsupportedMediaError(SuvixError):
    """The video input cannot be processed (missing file, unreadable, over limits)."""


class UnsupportedStrategyError(SuvixError):
    """The requested extraction strategy is not supported by this adapter/setup."""


class ProviderConfigError(SuvixError):
    """The adapter is misconfigured (missing credentials, unknown model)."""


class ProviderRequestError(SuvixError):
    """The provider call failed (network, API error, unexpected response)."""


class RateLimitError(ProviderRequestError):
    """The provider rate-limited the request."""


class ProviderTimeoutError(ProviderRequestError):
    """The provider call exceeded the configured timeout."""


class MalformedOutputError(SuvixError):
    """The provider returned output that could not be parsed as JSON."""


class SchemaValidationError(SuvixError):
    """The extracted data failed local JSON Schema validation (recovery disabled
    or no recovery budget configured). The report is in ``details``."""


class RecoveryExhaustedError(SuvixError):
    """Bounded recovery consumed its full budget without producing valid output."""


class MediaProcessingError(SuvixError):
    """Local media processing failed (ffprobe/ffmpeg error, bad timestamps)."""


class MissingEvidenceError(SuvixError):
    """Evidence was required but the extraction produced none usable."""


class ExtractionCancelledError(SuvixError):
    """Extraction was cancelled. Raised only for cooperative cancellation paths;
    raw ``asyncio.CancelledError`` from the event loop propagates unwrapped."""
