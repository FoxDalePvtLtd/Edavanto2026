"""
Best-effort ffprobe helper for VideoAsset.

If ffprobe is not installed, callers get (0, "") and should not fail.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Tuple

logger = logging.getLogger(__name__)


def _ffprobe_path() -> str | None:
    return shutil.which("ffprobe")


def probe_video(source) -> Tuple[int, str]:
    """
    Return (duration_seconds, resolution) for a Django UploadedFile or path.

    Returns (0, "") if ffprobe is unavailable or the probe fails.
    """
    ffprobe = _ffprobe_path()
    if not ffprobe:
        logger.info("ffprobe not installed; skipping video probe.")
        return (0, "")

    # Materialise to a temp file if we were given an UploadedFile.
    tmp_path = None
    try:
        if hasattr(source, "temporary_file_path"):
            path = source.temporary_file_path()
        elif hasattr(source, "read") and hasattr(source, "name"):
            # UploadedFile — copy to a temp file.
            suffix = Path(source.name).suffix or ".mp4"
            fd, tmp_path = tempfile.mkstemp(suffix=suffix)
            with open(fd, "wb") as out:
                for chunk in source.chunks():
                    out.write(chunk)
            path = tmp_path
        else:
            path = str(source)

        proc = subprocess.run(
            [
                ffprobe,
                "-v", "error",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if proc.returncode != 0:
            logger.warning("ffprobe failed: %s", proc.stderr.strip()[:300])
            return (0, "")

        data = json.loads(proc.stdout or "{}")

        # Duration from format (preferred) or video stream.
        duration = 0
        fmt = data.get("format") or {}
        try:
            duration = int(float(fmt.get("duration") or 0))
        except (TypeError, ValueError):
            duration = 0

        # Resolution from the first video stream.
        resolution = ""
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                w = stream.get("width")
                h = stream.get("height")
                if w and h:
                    resolution = f"{w}x{h}"
                if not duration:
                    try:
                        duration = int(float(stream.get("duration") or 0))
                    except (TypeError, ValueError):
                        pass
                break

        return (duration, resolution)

    except Exception as exc:
        logger.warning("probe_video error: %s", exc)
        return (0, "")

    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass