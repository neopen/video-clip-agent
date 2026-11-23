"""SceneDetectService 阈值与分段单元测试。"""

import pytest

from penclip.services.scene_detect_service import SceneDetectService


def _samples(*diffs):
    return [
        {"time": float(index), "diff": diff, "brightness": 100.0, "hue": 60.0}
        for index, diff in enumerate(diffs)
    ]


def test_adaptive_threshold_detects_hard_cut_below_legacy_cutoff():
    """实测硬切只有 0.27~0.41，遗留固定阈值 0.6 会全部漏检。"""
    service = SceneDetectService()

    threshold = service._resolve_threshold(_samples(0.02, 0.03, 0.02, 0.35, 0.01, 0.02))

    assert threshold < 0.35


def test_adaptive_threshold_keeps_floor_on_uniform_footage():
    service = SceneDetectService()

    threshold = service._resolve_threshold(_samples(0.0, 0.001, 0.0, 0.002))

    assert threshold == pytest.approx(0.05)


def test_configured_threshold_is_used_verbatim():
    service = SceneDetectService({"scene_threshold": 0.4})

    assert service._resolve_threshold(_samples(0.01, 0.9)) == pytest.approx(0.4)


def test_lower_sensitivity_lowers_threshold():
    # MAD 为 0 时阈值只会落在 0.05 下限，因此构造有离散度的样本序列
    samples = _samples(0.1, 0.2, 0.1, 0.2, 0.9, 0.8)

    loose = SceneDetectService({"threshold_sensitivity": 2.0})._resolve_threshold(samples)
    strict = SceneDetectService({"threshold_sensitivity": 12.0})._resolve_threshold(samples)

    assert loose < strict
    assert loose < 0.9 <= strict


@pytest.fixture
def fake_detection(monkeypatch):
    """Replace the OpenCV sampling tool so tests stay independent of video files."""
    pytest.importorskip("cv2")
    import penclip.tools.scene_recognition_tool as tool_module

    class _Tool:
        def __init__(self, samples, duration):
            self._samples = samples
            self._duration = duration

        def sample_frame_differences(self, video_path):
            return {
                "success": True,
                "video_info": {"duration": self._duration},
                "samples": self._samples,
            }

    state = {"samples": [], "duration": 0.0}

    def factory(config=None):
        return _Tool(state["samples"], state["duration"])

    monkeypatch.setattr(tool_module, "get_scene_recognition_tool", factory)
    return state


def test_detect_scenes_splits_at_cuts(fake_detection):
    fake_detection["duration"] = 12.0
    fake_detection["samples"] = _samples(0.02, 0.03, 0.02, 0.55, 0.01, 0.02, 0.03, 0.60, 0.01,
                                         0.02, 0.03, 0.01)

    scenes = SceneDetectService().detect_scenes("any.mp4")

    assert [s["start_time"] for s in scenes] == [0.0, 3.0, 7.0]
    assert scenes[-1]["end_time"] == 12.0
    assert scenes[0]["descriptor"]["hue"] == 60.0


def test_detect_scenes_returns_whole_video_without_cuts(fake_detection):
    fake_detection["duration"] = 8.0
    fake_detection["samples"] = _samples(*[0.01] * 8)

    scenes = SceneDetectService().detect_scenes("any.mp4")

    assert len(scenes) == 1
    assert scenes[0] == {
        "start_time": 0.0, "end_time": 8.0, "duration": 8.0,
        "descriptor": {"brightness": 100.0, "hue": 60.0},
    }


def test_segment_video_merges_short_fragments_forward(monkeypatch):
    service = SceneDetectService({"min_segment_duration": 3.0})
    monkeypatch.setattr(service, "detect_scenes", lambda _path: [
        {"start_time": 0.0, "end_time": 1.0, "duration": 1.0, "descriptor": {}},
        {"start_time": 1.0, "end_time": 2.0, "duration": 1.0, "descriptor": {}},
        {"start_time": 2.0, "end_time": 8.0, "duration": 6.0, "descriptor": {}},
    ])

    segments = service.segment_video("any.mp4")

    assert len(segments) == 1
    assert (segments[0]["start_time"], segments[0]["end_time"]) == (0.0, 8.0)


def test_segment_video_keeps_coverage_gapless(monkeypatch):
    service = SceneDetectService({"min_segment_duration": 2.0})
    monkeypatch.setattr(service, "detect_scenes", lambda _path: [
        {"start_time": 0.0, "end_time": 4.0, "duration": 4.0, "descriptor": {}},
        {"start_time": 4.0, "end_time": 5.0, "duration": 1.0, "descriptor": {}},
    ])

    segments = service.segment_video("any.mp4")

    assert segments[0]["end_time"] == 5.0
    assert sum(s["duration"] for s in segments) == pytest.approx(5.0)
