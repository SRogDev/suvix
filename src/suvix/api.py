"""Public API: the ``Suvix`` entry point.

Async-first by design (ADR-001). Blocking media work is offloaded to threads
by the media layer (Milestone 2); provider calls are natively async.

Cancellation: cancelling the ``extract`` task propagates
``asyncio.CancelledError`` unwrapped — it is never converted into an
apparently successful empty result.
"""

from __future__ import annotations

from typing import Any

from suvix.adapters.base import VideoExtractor
from suvix.contracts import ExtractionResult
from suvix.extraction import run_extraction
from suvix.options import ExtractionOptions


class Suvix:
    """Schema-guided video data extraction.

    Example:
        extractor = GeminiExtractor()  # Milestone 3
        suvix = Suvix()
        result = await suvix.extract(
            video="sample.mp4",
            schema=Extraction.model_json_schema(),
            instructions="Identify each visible event of interest.",
            extractor=extractor,
        )
    """

    async def extract(
        self,
        *,
        video: str | Any,
        schema: dict[str, Any],
        instructions: str,
        extractor: VideoExtractor,
        options: ExtractionOptions | None = None,
    ) -> ExtractionResult:
        """Extract structured data from a video.

        Args:
            video: Local video file path (``str`` or ``os.PathLike``).
                Remote URLs are not supported yet.
            schema: JSON Schema (Draft 2020-12) describing the desired output.
                Validated locally before any provider call.
            instructions: What information to extract. Kept separate from
                untrusted content observed inside the video.
            extractor: Explicitly chosen provider adapter. Suvix never
                replaces the developer's choice.
            options: Bounded extraction configuration
                (:class:`ExtractionOptions`); conservative defaults apply.

        Raises:
            InvalidInputError: malformed video reference or instructions.
            UnsupportedSchemaError: the schema is not valid Draft 2020-12.
            UnsupportedStrategyError: the strategy is unsupported by the
                adapter, or ``selected_frames`` (Milestone 5, not yet built).
            ProviderRequestError (incl. RateLimitError, ProviderTimeoutError):
                the provider call failed.
            MalformedOutputError: provider output was not parseable JSON.
            SchemaValidationError: output failed local validation and no
                recovery budget was configured.
            RecoveryExhaustedError: bounded recovery used up its attempts.
        """
        return await run_extraction(
            video=video,
            schema=schema,
            instructions=instructions,
            extractor=extractor,
            options=options,
        )
