"""SceneDetectService — scene boundary detection for video segmentation."""

from typing import Any, Dict, List, Optional

from penclip.logger import info, warning

DEFAULT_CONFIG = {
    "min_segment_duration": 2.0,
    "frame_interval": 1.0,
    # None = adaptive (robust outlier rule): hard cuts sit at 0.27-0.41 in
    # measured footage, so the legacy fixed 0.6 cutoff detected nothing.
    # A numeric value is used as the sole cutoff instead.
    "scene_threshold": None,
    "threshold_sensitivity": 8.0,
}


class SceneDetectService:
    """Delegates to penclip.tools.scene_recognition_tool (OpenCV histogram diff)."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = {**DEFAULT_CONFIG, **(config or {})}

    def detect_scenes(self, video_path: str) -> List[Dict[str, Any]]:
        """Return scene boundaries as [{start_time, end_time, duration}, ...]."""
        from penclip.tools.scene_recognition_tool import get_scene_recognition_tool

        tool = get_scene_recognition_tool({"frame_interval": self._config["frame_interval"]})
        result = tool.sample_frame_differences(video_path)
        if not result.get("success"):
            warning(f"SceneDetectService: detection failed for {video_path}: {result.get('error', 'unknown')}")
            return []

        duration = (result.get("video_info") or {}).get("duration", 0.0)
        samples = result.get("samples") or []
        if not samples or not duration:
            return []

        threshold = self._resolve_threshold(samples)
        cuts = [s["time"] for s in samples if s["diff"] > threshold]

        scenes = []
        start = 0.0
        for cut in cuts:
            if cut > start:
                scenes.append(self._make_scene(samples, start, cut))
                start = cut
        if duration > start:
            scenes.append(self._make_scene(samples, start, duration))

        info(f"SceneDetectService: {video_path} -> {len(scenes)} scene(s) at threshold {threshold:.4f}")
        return scenes

    def segment_video(self, video_path: str, min_duration: Optional[float] = None) -> List[Dict[str, Any]]:
        """Detect scenes then merge short fragments so the timeline stays gapless.

        Fragmented scenes are the documented V0.1 risk; merging forwards keeps
        total coverage intact instead of dropping the short tail.
        """
        floor = min_duration if min_duration is not None else self._config["min_segment_duration"]
        scenes = self.detect_scenes(video_path)
        if not scenes:
            return []

        merged: List[Dict[str, Any]] = []
        for scene in scenes:
            if merged and merged[-1]["duration"] < floor:
                last = merged[-1]
                last["end_time"] = scene["end_time"]
                last["duration"] = last["end_time"] - last["start_time"]
                continue
            merged.append(dict(scene))

        if len(merged) > 1 and merged[-1]["duration"] < floor:
            last = merged.pop()
            merged[-1]["end_time"] = last["end_time"]
            merged[-1]["duration"] = merged[-1]["end_time"] - merged[-1]["start_time"]

        info(f"SceneDetectService: {video_path} -> {len(scenes)} scene(s), {len(merged)} segment(s) after merge")
        return merged

    def _resolve_threshold(self, samples: List[Dict[str, Any]]) -> float:
        """Pick a cut threshold: fixed when configured, else median + k × MAD."""
        fixed = self._config.get("scene_threshold")
        if fixed is not None:
            return float(fixed)

        diffs = sorted(s["diff"] for s in samples)
        median = self._percentile(diffs, 0.5)
        mad = self._percentile(sorted(abs(d - median) for d in diffs), 0.5)
        sensitivity = float(self._config.get("threshold_sensitivity", 8.0))
        floor = 0.05
        return max(floor, median + sensitivity * mad)

    @staticmethod
    def _percentile(sorted_values: List[float], ratio: float) -> float:
        if not sorted_values:
            return 0.0
        index = min(len(sorted_values) - 1, max(0, int(ratio * (len(sorted_values) - 1))))
        return sorted_values[index]

    @staticmethod
    def _make_scene(samples: List[Dict[str, Any]], start: float, end: float) -> Dict[str, Any]:
        """Build a scene dict with averaged visual stats over its time range."""
        inside = [s for s in samples if start <= s["time"] < end] or samples
        brightness = sum(float(s.get("brightness") or 0.0) for s in inside) / len(inside)
        hues = [float(s["hue"]) for s in inside if s.get("hue") is not None]
        return {
            "start_time": float(start),
            "end_time": float(end),
            "duration": float(end) - float(start),
            "descriptor": {
                "brightness": round(brightness, 2),
                "hue": round(sum(hues) / len(hues), 1) if hues else None,
            },
        }
