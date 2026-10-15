#!/usr/bin/env python3
"""Generate the synthetic benchmark fixture videos for Suvix Milestone 8.

These fixtures validate the *benchmark harness* (task loading, baseline
execution, metric computation) — not provider accuracy. Every expectation in
``benchmarks/tasks/*.json`` is annotated from the generation parameters
below, never from a model.

Requirements: ``ffmpeg`` on PATH with libx264 and the drawtext filter.

Reproducibility: identical ffmpeg builds and identical commands produce
identical videos; the script prints each file's sha256 so a benchmark run
can be tied to the exact fixture bytes. Generated files are gitignored
(``*.mp4``) — regenerate with this script instead of committing binaries.

Usage:
    python benchmarks/fixtures/generate.py
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
SIZE = "320x240"
FPS = "15"

FIXTURES = Path(__file__).resolve().parent


def run(cmd: list[str], out: Path) -> None:
    print(f"$ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    print(f"  wrote {out.name} ({out.stat().st_size} bytes) sha256={digest}")


def temporal_flashes() -> None:
    """8s black video; the word FLASH appears at t=2..3s and t=5..6s.

    Expected: two ``flash`` events at 2.5s and 5.5s (tolerance 1.0s).
    """
    out = FIXTURES / "temporal_flashes.mp4"
    draw = (
        f"drawtext=fontfile={FONT}:text='FLASH':fontsize=48:fontcolor=white:"
        f"x=(w-text_w)/2:y=(h-text_h)/2:enable='between(t,2,3)+between(t,5,6)'"
    )
    run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"color=c=black:s={SIZE}:d=8:r={FPS}",
            "-vf", draw,
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(out),
        ],
        out,
    )


def objects_counts() -> None:
    """6s white video with three filled red squares.

    Expected: ``{"red_square": 3}``. Squares are static for the whole clip,
    so frame sampling cannot change the count.
    """
    out = FIXTURES / "objects_counts.mp4"
    boxes = ",".join(
        f"drawbox=x={x}:y=90:w=60:h=60:c=red:t=fill" for x in (40, 130, 220)
    )
    run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"color=c=white:s={SIZE}:d=6:r={FPS}",
            "-vf", boxes,
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(out),
        ],
        out,
    )


def visible_text() -> None:
    """8s black video; the scoreboard text appears at t=2..4s.

    Expected: ``scoreboard == "SCORE 3-1"`` (normalized comparison).
    """
    out = FIXTURES / "visible_text.mp4"
    draw = (
        f"drawtext=fontfile={FONT}:text='SCORE 3-1':fontsize=40:fontcolor=white:"
        f"x=(w-text_w)/2:y=(h-text_h)/2:enable='between(t,2,4)'"
    )
    run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"color=c=black:s={SIZE}:d=8:r={FPS}",
            "-vf", draw,
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(out),
        ],
        out,
    )


def main() -> int:
    missing = [p for p in (FONT,) if not Path(p).exists()]
    if missing:
        print(f"missing required font files: {missing}", file=sys.stderr)
        return 1
    temporal_flashes()
    objects_counts()
    visible_text()
    print("done. Fixture videos are gitignored; regenerate, don't commit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
