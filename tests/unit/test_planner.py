"""Rule-based strategy planner: explainable, no LLM, never switches provider."""

import pytest

from suvix.adapters.base import ExtractorCapabilities
from suvix.errors import UnsupportedStrategyError
from suvix.options import ExtractionOptions
from suvix.planner import select_strategy


def _caps(**overrides):
    base = dict(provider="fake", model="fake-1", native_video=True,
                image_input=True, multi_image=True)
    base.update(overrides)
    return ExtractorCapabilities(**base)


def test_auto_prefers_native_video_when_supported():
    decision = select_strategy(capabilities=_caps(), options=ExtractionOptions())
    assert decision.strategy == "native_video"
    assert decision.reason  # the choice must be explained


def test_auto_falls_back_to_selected_frames_without_native_video():
    decision = select_strategy(
        capabilities=_caps(native_video=False), options=ExtractionOptions())
    assert decision.strategy == "selected_frames"


def test_auto_fails_when_adapter_supports_neither_input():
    with pytest.raises(UnsupportedStrategyError):
        select_strategy(
            capabilities=_caps(native_video=False, image_input=False,
                              multi_image=False),
            options=ExtractionOptions())


def test_explicit_native_video_honored():
    decision = select_strategy(
        capabilities=_caps(), options=ExtractionOptions(strategy="native_video"))
    assert decision.strategy == "native_video"
    assert "explicit" in decision.reason.lower()


def test_explicit_selected_frames_honored_when_images_supported():
    decision = select_strategy(
        capabilities=_caps(native_video=True),
        options=ExtractionOptions(strategy="selected_frames"))
    assert decision.strategy == "selected_frames"


def test_explicit_strategy_rejected_when_unsupported():
    with pytest.raises(UnsupportedStrategyError) as exc:
        select_strategy(
            capabilities=_caps(native_video=False),
            options=ExtractionOptions(strategy="native_video"))
    assert "native_video" in str(exc.value)


def test_planner_never_mentions_switching_provider():
    decision = select_strategy(capabilities=_caps(), options=ExtractionOptions())
    assert "switch" not in decision.reason.lower()


def test_scene_sampling_flagged_for_selected_frames():
    decision = select_strategy(
        capabilities=_caps(native_video=False),
        options=ExtractionOptions(sampling="scene_changes"))
    assert decision.strategy == "selected_frames"
    assert decision.sampling == "scene_changes"
    assert decision.requires_scene_sampling is True
    assert "Scene-change sampling" in decision.reason


def test_scene_sampling_ignored_for_native_video():
    decision = select_strategy(
        capabilities=_caps(),
        options=ExtractionOptions(sampling="scene_changes"))
    assert decision.strategy == "native_video"
    assert decision.sampling == "uniform"
    assert decision.requires_scene_sampling is False


def test_default_sampling_is_uniform():
    decision = select_strategy(
        capabilities=_caps(native_video=False), options=ExtractionOptions())
    assert decision.sampling == "uniform"
    assert decision.requires_scene_sampling is False
