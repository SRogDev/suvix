"""Frame timestamp sampling strategies.

Sampling is provider-neutral and fully deterministic: the same duration and
limits always produce the same timestamps. Timestamps are in seconds, ordered
ascending, measured from the start of the video.
"""

from suvix.sampling.base import Sampler
from suvix.sampling.uniform import uniform_timestamps

__all__ = ["Sampler", "uniform_timestamps"]
