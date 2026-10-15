"""Rule-based strategy selection.

``auto`` is a small, explainable planner: no LLM call, no provider switching,
and the decision (plus a concise reason) is recorded in execution metadata.
The developer can always override with an explicit strategy.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict

from suvix.adapters.base import ExtractorCapabilities
from suvix.errors import UnsupportedStrategyError
from suvix.options import ExtractionOptions


class StrategyDecision(BaseModel):
    """The selected strategy and the human-readable reason for it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy: str
    reason: str


def select_strategy(
    *,
    capabilities: ExtractorCapabilities,
    options: ExtractionOptions,
    hints: Mapping[str, Any] | None = None,
) -> StrategyDecision:
    """Choose ``native_video`` or ``selected_frames``.

    ``hints`` is reserved for media/task signals (duration, temporal-detail
    needs); Milestone 1 ignores it, Milestone 5 may use it. It never changes
    the provider.
    """
    requested = options.strategy
    if requested != "auto":
        _require_supported(requested, capabilities)
        return StrategyDecision(
            strategy=requested,
            reason=f"Strategy explicitly requested by the developer: {requested}.",
        )

    if capabilities.native_video:
        return StrategyDecision(
            strategy="native_video",
            reason=(
                f"Adapter {capabilities.provider}/{capabilities.model} supports "
                "native video input; auto-selected native_video for full "
                "temporal context with no local preprocessing."
            ),
        )
    if capabilities.image_input or capabilities.multi_image:
        return StrategyDecision(
            strategy="selected_frames",
            reason=(
                f"Adapter {capabilities.provider}/{capabilities.model} does not "
                "support native video input; auto-selected selected_frames "
                "using the adapter's image input."
            ),
        )
    raise UnsupportedStrategyError(
        f"Adapter {capabilities.provider}/{capabilities.model} supports neither "
        "native video nor image input; no extraction strategy is available.",
        details={"provider": capabilities.provider, "model": capabilities.model},
    )


def _require_supported(strategy: str, capabilities: ExtractorCapabilities) -> None:
    if strategy == "native_video" and not capabilities.native_video:
        raise UnsupportedStrategyError(
            f"Strategy 'native_video' was explicitly requested, but adapter "
            f"{capabilities.provider}/{capabilities.model} does not support "
            "native video input. Suvix will not silently substitute another "
            "strategy; choose 'selected_frames' or another adapter.",
            details={"strategy": strategy, "provider": capabilities.provider,
                     "model": capabilities.model},
        )
    if strategy == "selected_frames" and not (
        capabilities.image_input or capabilities.multi_image
    ):
        raise UnsupportedStrategyError(
            f"Strategy 'selected_frames' was explicitly requested, but adapter "
            f"{capabilities.provider}/{capabilities.model} does not accept "
            "image input.",
            details={"strategy": strategy, "provider": capabilities.provider,
                     "model": capabilities.model},
        )
