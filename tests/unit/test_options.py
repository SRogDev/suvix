"""ExtractionOptions: small typed config object with conservative defaults."""

import pytest
from pydantic import ValidationError

from suvix.options import STRATEGIES, ExtractionOptions


def test_defaults_are_conservative():
    opts = ExtractionOptions()
    assert opts.strategy == "auto"
    assert opts.max_frames >= 1
    assert opts.max_refinement_rounds <= 3
    assert opts.max_recovery_attempts <= 3
    assert opts.enable_recovery is True
    assert opts.require_evidence is False
    assert opts.collect_usage is True


def test_strategies_are_the_documented_trio():
    assert set(STRATEGIES) == {"auto", "native_video", "selected_frames"}


def test_unknown_strategy_rejected():
    with pytest.raises(ValidationError):
        ExtractionOptions(strategy="magic")  # type: ignore[arg-type]


def test_negative_budgets_rejected():
    with pytest.raises(ValidationError):
        ExtractionOptions(max_frames=0)
    with pytest.raises(ValidationError):
        ExtractionOptions(max_recovery_attempts=-1)
    with pytest.raises(ValidationError):
        ExtractionOptions(max_refinement_rounds=-1)


def test_explicit_values_accepted():
    opts = ExtractionOptions(strategy="native_video", max_frames=16,
                             enable_recovery=False)
    assert opts.strategy == "native_video"
    assert opts.max_frames == 16
    assert opts.enable_recovery is False


def test_unknown_fields_rejected():
    with pytest.raises(ValidationError):
        ExtractionOptions(no_such_option=1)  # type: ignore[call-arg]


def test_sampling_defaults_to_uniform():
    opts = ExtractionOptions()
    assert opts.sampling == "uniform"
    assert opts.scene_threshold == 0.4
    assert opts.scene_floor_fraction == 0.5


def test_scene_sampling_options_accepted_and_bounded():
    opts = ExtractionOptions(sampling="scene_changes", scene_threshold=0.0,
                             scene_floor_fraction=1.0)
    assert opts.sampling == "scene_changes"
    with pytest.raises(ValidationError):
        ExtractionOptions(sampling="bogus")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        ExtractionOptions(scene_threshold=1.5)
    with pytest.raises(ValidationError):
        ExtractionOptions(scene_floor_fraction=-0.1)
