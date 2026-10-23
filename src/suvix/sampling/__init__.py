"""Frame timestamp sampling strategies.

Sampling is provider-neutral and fully deterministic: the same duration and
limits always produce the same timestamps. Timestamps are in seconds, ordered
ascending, measured from the start of the video.
"""

from suvix.sampling.base import Sampler
from suvix.sampling.scene_changes import (
    make_scene_sampler,
    merge_with_uniform_floor,
    scene_change_timestamps,
)
from suvix.sampling.uniform import uniform_timestamps

__all__ = [
    "Sampler",
    "make_scene_sampler",
    "merge_with_uniform_floor",
    "scene_change_timestamps",
    "uniform_timestamps",
]
