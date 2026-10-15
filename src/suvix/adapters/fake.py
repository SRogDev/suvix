"""Deterministic fake adapter for tests and offline development.

The script is an explicit list of outcomes consumed in order; when exhausted,
the last outcome repeats. Script items:

- ``{"data": {...}, "evidence": [...], "usage": {...}}`` — successful extraction.
- ``{"raw_text": "..."}`` — provider returned text instead of parsed data
  (malformed when the text is not valid JSON).
- ``{"error": <exception>}`` — raise the exception (e.g. ProviderRequestError).

Every call is recorded in :attr:`calls` for assertions.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from suvix.adapters.base import (
    AdapterRequest,
    ExtractorCapabilities,
    ProviderExtraction,
    VideoExtractor,
)


class FakeExtractor:
    """Scripted :class:`VideoExtractor` with no network access."""

    def __init__(
        self,
        *,
        provider: str = "fake",
        model: str = "fake-1",
        script: list[dict[str, Any]] | None = None,
        capabilities: ExtractorCapabilities | None = None,
    ) -> None:
        self._provider = provider
        self._model = model
        self._script: deque[dict[str, Any]] = deque(script or [{"data": {}}])
        self._last: dict[str, Any] = {"data": {}}
        self._capabilities = capabilities or ExtractorCapabilities(
            provider=provider,
            model=model,
            native_video=True,
            image_input=True,
            multi_image=True,
            structured_output=True,
            usage_metadata=True,
            timestamp_support=True,
            notes="Deterministic test double; not a real provider.",
        )
        self.calls: list[AdapterRequest] = []

    @property
    def name(self) -> str:
        return f"{self._provider}/{self._model}"

    @property
    def capabilities(self) -> ExtractorCapabilities:
        return self._capabilities

    async def extract(self, request: AdapterRequest) -> ProviderExtraction:
        self.calls.append(request)
        item = self._script.popleft() if self._script else self._last
        self._last = item
        if "error" in item:
            raise item["error"]
        return ProviderExtraction(
            data=item.get("data"),
            raw_text=item.get("raw_text"),
            evidence=item.get("evidence", []),
            usage=item.get("usage", {}),
            warnings=item.get("warnings", []),
        )


assert isinstance(FakeExtractor(), VideoExtractor)  # protocol conformance
