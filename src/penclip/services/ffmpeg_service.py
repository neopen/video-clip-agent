"""FFmpegService — unified interface for FFmpeg operations."""

import shutil
from typing import Any, Dict, List, Optional

from penclip.logger import debug, error, info


DEFAULT_CONFIG = {
    "output_dir": "data/output",
    "ffmpeg_bin": "ffmpeg",
}


class FFmpegService:
    """Delegates to penclip.utils.ffmpeg_* modules for actual execution."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = {**DEFAULT_CONFIG, **(config or {})}
        debug("FFmpegService initialized")

    def cut_segment(self, input_path: str, start: float, end: float, output_path: str) -> bool:
        from penclip.utils.ffmpeg_utils import FFmpegUtils

        ok = FFmpegUtils.extract_video_clip(input_path, output_path, start, end)
        if not ok:
            error(f"FFmpegService: cut failed {input_path} [{start}-{end}] -> {output_path}")
        return ok

    def concat_clips(self, clip_paths: List[str], output_path: str,
                     config: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Concat clips into one video; returns the output path, or None on failure.

        Uses the transcoding render path so heterogeneous sources share one
        codec — the precondition for gapless joins without audio/video drift.
        """
        from penclip.utils.ffmpeg_utils import FFmpegUtils

        result = FFmpegUtils.render_video(clip_paths, output_path, config=config or {})
        if result is None:
            error(f"FFmpegService: concat failed for {len(clip_paths)} clip(s) -> {output_path}")
            return None
        info(f"FFmpegService: rendered {len(clip_paths)} clip(s) -> {result}")
        return result

    def get_metadata(self, video_path: str) -> Dict[str, Any]:
        from penclip.utils.ffmpeg_run_utils import get_video_info

        return get_video_info(video_path) or {}

    def is_available(self) -> bool:
        """Report whether an ffmpeg binary can actually be invoked."""
        return shutil.which(self._config.get("ffmpeg_bin", "ffmpeg")) is not None
