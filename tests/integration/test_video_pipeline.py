"""端到端出片测试 —— V0.1 验收标准：3 段素材合成可播放视频，无黑场、音画同步。

需要本机 ffmpeg（以及 OpenCV 做黑场抽检）；缺失时整个模块 skip。
"""

import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from penclip.agents.analyzer import AnalyzerAgent
from penclip.agents.asset_agent import AssetAgent
from penclip.agents.composer import ComposerAgent
from penclip.agents.matcher import MatcherAgent
from penclip.agents.planner import PlannerAgent
from penclip.agents.state_agent import StateAgent
from penclip.core.hub.central_hub import CentralHub
from penclip.core.state.state_manager import get_state_manager
from penclip.domain.entities.slot import Slot

COLORS = (("red", 440), ("green", 660), ("blue", 880))
COLOUR_LABELS = {"red": "色调:红色", "green": "色调:绿色", "blue": "色调:蓝色"}
CLIP_DURATION = 6.0

_ffmpeg = shutil.which("ffmpeg")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.skipif(not _ffmpeg, reason="ffmpeg not available"),
]


def _make_clip(path: Path, colour: str, frequency: int) -> None:
    subprocess.run(
        [
            _ffmpeg, "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={colour}:s=640x360:d={CLIP_DURATION}",
            "-f", "lavfi", "-i", f"sine=frequency={frequency}:duration={CLIP_DURATION}",
            "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", str(path),
        ],
        check=True,
    )


def _streams(path: Path):
    """独立实现的分流时长探测，避免复用被测代码的判定。"""
    ffprobe = shutil.which("ffprobe")
    output = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "stream=codec_type,duration",
         "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    streams = {}
    for line in output.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2 and parts[1]:
            streams[parts[0]] = float(parts[1])
    return streams


@pytest.fixture(scope="module")
def source_clips(tmp_path_factory):
    root = tmp_path_factory.mktemp("media")
    paths = []
    for colour, frequency in COLORS:
        path = root / f"solid_{colour}.mp4"
        _make_clip(path, colour, frequency)
        paths.append(path)
    return paths


def _register_assets(source_clips) -> str:
    session_id = f"e2e_{uuid4().hex[:8]}"
    for path in source_clips:
        result = AssetAgent().execute({"url": str(path)}, {"session_id": session_id})
        assert result.success is True, result.message
    return session_id


def _add_colour_slots(session_id: str) -> None:
    manager = get_state_manager()
    state = manager.get_session(session_id)
    state.slots = []
    for position, (colour, _) in enumerate(COLORS):
        state.slots.append(Slot(
            position=position, semantic_query=f"{COLOUR_LABELS[colour]}开头",
            min_duration=3.0, max_duration=10.0))
    manager.update_session(state)


@pytest.fixture(scope="module")
def matched_session(source_clips):
    """素材登记 → 分析 → 规划 → 匹配后的会话，供各用例只读断言。

    每个用例都只读取这份状态（合成用例另写自己的输出目录），不依赖执行顺序。
    """
    session_id = _register_assets(source_clips)

    analyzed = AnalyzerAgent().execute({}, {"session_id": session_id})
    assert analyzed.success is True, analyzed.message

    _add_colour_slots(session_id)
    matched = MatcherAgent().execute({}, {"session_id": session_id})
    assert matched.success is True, matched.message
    return session_id


def test_analysis_produces_one_segment_per_clip_with_colour_labels(matched_session):
    state = get_state_manager().get_session(matched_session)

    segments = [s for result in state.analysis_results.values() for s in result.segments]
    labels = {label for s in segments for label in s.labels}

    assert len(segments) == len(COLORS)
    assert all(label in labels for label in COLOUR_LABELS.values())


def test_matcher_fills_every_slot(matched_session):
    state = get_state_manager().get_session(matched_session)

    assert len(state.match_results) == len(COLORS)
    assert all(r.candidates for r in state.match_results.values())
    # 三个色调槽位应各自选中最贴合的片段，不重复占用
    assert len({r.candidates[0].segment_id for r in state.match_results.values()}) == len(COLORS)


def test_compose_outputs_synced_bright_video(matched_session, tmp_path):
    rendered = ComposerAgent(config={
        "output_dir": str(tmp_path),
        "clip_dir": str(tmp_path / "clips"),
    }).execute({"intent": "state_render"}, {"session_id": matched_session})

    assert rendered.success is True, rendered.message
    output = Path(rendered.data["output_path"])
    assert output.is_file() and output.stat().st_size > 0

    streams = _streams(output)
    assert {"video", "audio"} <= set(streams)
    assert abs(streams["video"] - streams["audio"]) <= 0.5

    cv2 = pytest.importorskip("cv2")
    capture = cv2.VideoCapture(str(output))
    fps = capture.get(cv2.CAP_PROP_FPS) or 24.0
    frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    try:
        assert frames >= int(streams["video"] * fps * 0.9)
        for second in (1.0, streams["video"] / 2, streams["video"] - 1.0):
            capture.set(cv2.CAP_PROP_POS_FRAMES, int(second * fps))
            ok, frame = capture.read()
            assert ok, f"第 {second:.1f} 秒无法解码"
            # 黑场 = 全帧接近 0；纯色素材合成后每帧都应有明显亮度
            assert frame.mean() > 30.0, f"第 {second:.1f} 秒疑似黑场，均亮度 {frame.mean():.1f}"
    finally:
        capture.release()


def test_hub_routes_natural_language_through_the_pipeline(source_clips):
    """真实用户旅程：每条指令都走 CentralHub，高风险步骤经确认门才执行。"""
    session_id = f"hub_{uuid4().hex[:8]}"
    hub = CentralHub()
    for agent in (PlannerAgent(), AssetAgent(), AnalyzerAgent(), MatcherAgent(), StateAgent()):
        hub.register_agent(agent)

    for path in source_clips:
        assert hub.process(str(path), session_id).success is True

    planned = hub.process("做个混剪：红色开头，绿色中间，蓝色结尾", session_id)
    assert planned.needs_confirmation is True
    assert hub.process("查看进度", session_id).data["slots"] == 0

    assert hub.confirm(session_id).success is True
    assert hub.process("分析素材", session_id).success is True
    matched = hub.process("匹配片段", session_id)
    assert matched.success is True, matched.message

    progress = hub.process("查看进度", session_id)
    assert progress.data["phase"] == "matched"
    assert progress.data["matched_slots"] == len(COLORS)
    assert progress.data["undo_depth"] >= 5

    undone = hub.process("撤销", session_id)
    assert undone.success is True, undone.message
    assert hub.process("查看进度", session_id).data["phase"] == "analyzed"
