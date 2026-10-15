"""Local media processing: metadata inspection, frame extraction, segments.

All media work shells out to the optional external ``ffprobe``/``ffmpeg``
binaries and offloads blocking calls to threads (public functions are
``async``). Temporary files live in a managed temp directory that is always
cleaned up; public results carry image bytes in memory, never temp paths.
"""

from suvix.media.frames import FrameRegistry, SampledFrame, extract_frames_at, make_frame_id
from suvix.media.metadata import VideoMetadata, inspect_video
from suvix.media.segments import Segment, split_into_segments, to_global_seconds

__all__ = [
    "FrameRegistry",
    "SampledFrame",
    "Segment",
    "VideoMetadata",
    "extract_frames_at",
    "inspect_video",
    "make_frame_id",
    "split_into_segments",
    "to_global_seconds",
]
