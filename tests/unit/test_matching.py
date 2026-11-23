"""MatcherAgent 标签打分单元测试（V0.1 策略：标签重叠 + 时长约束，非向量检索）。"""

from uuid import uuid4

from penclip.agents.analyzer import AnalyzerAgent
from penclip.agents.matcher import MatcherAgent
from penclip.core.state.state_manager import get_state_manager
from penclip.domain.entities.assembly_state import AnalysisResult, AssemblyState
from penclip.domain.entities.segment import Segment
from penclip.domain.entities.slot import Slot
from penclip.domain.entities.video_asset import AssetStatus, VideoAsset

SEGMENTS = [
    {"segment_id": "seg_red", "labels": ["来源:e2e_red", "色调:红色", "明亮", "横屏"],
     "start_time": 0.0, "end_time": 6.0},
    {"segment_id": "seg_blue", "labels": ["来源:e2e_blue", "色调:蓝色", "昏暗", "竖屏"],
     "start_time": 0.0, "end_time": 4.0},
]


def _slot(query, **kwargs):
    data = {"slot_id": f"slot_{uuid4().hex[:6]}", "semantic_query": query,
            "min_duration": 3.0, "max_duration": 10.0}
    data.update(kwargs)
    return data


def test_hue_bands_match_pure_colours():
    assert AnalyzerAgent._hue_name(0) == "红色"
    assert AnalyzerAgent._hue_name(19) == "橙色"
    assert AnalyzerAgent._hue_name(30) == "黄色"
    assert AnalyzerAgent._hue_name(60) == "绿色"
    assert AnalyzerAgent._hue_name(90) == "青色"
    assert AnalyzerAgent._hue_name(120) == "蓝色"
    assert AnalyzerAgent._hue_name(175) == "红色"


def test_build_labels_covers_source_colour_and_orientation():
    asset = VideoAsset(filename="e2e_green.mp4", width=1920, height=1080,
                       status=AssetStatus.ANALYZED)

    labels = AnalyzerAgent._build_labels(asset, {"brightness": 120, "hue": 60}, duration=12.0)

    assert "来源:e2e_green" in labels
    assert "色调:绿色" in labels
    assert "中等亮度" in labels
    assert "长镜头" in labels
    assert "横屏" in labels


def test_label_score_prefers_structured_tags():
    assert MatcherAgent._label_score("红色放开头", ["色调:红色"]) == 1.0
    assert MatcherAgent._label_score("用 e2e_blue 的画面", ["来源:e2e_blue"]) == 1.0
    assert MatcherAgent._label_score("明亮", ["明亮"]) == 0.5
    # 无结构化命中的兜底最多 0.4，避免弱相似冲掉真实标签命中
    assert MatcherAgent._label_score("海边日落", ["色调:蓝色"]) <= 0.4


def test_duration_score_is_flat_inside_range_and_decays_outside():
    slot = _slot("任意", min_duration=4.0, max_duration=8.0)

    assert MatcherAgent._duration_score(6.0, slot) == 1.0
    assert 0.0 < MatcherAgent._duration_score(12.0, slot) < 1.0
    assert MatcherAgent._duration_score(30.0, slot) == 0.0


def test_semantic_search_ranks_best_segment_first():
    agent = MatcherAgent()

    ranked = agent._rank_by_similarity(
        agent._semantic_search("蓝色昏暗竖屏", SEGMENTS, _slot("蓝色昏暗竖屏")))

    assert ranked[0].segment_id == "seg_blue"
    assert ranked[0].similarity_score > ranked[-1].similarity_score


def test_source_constraint_restricts_candidates():
    agent = MatcherAgent()
    all_candidates = agent._semantic_search("片段", SEGMENTS, _slot("片段"))

    constrained = agent._apply_constraints(all_candidates, {"source_constraint": "e2e_red"}, SEGMENTS)

    assert [c.segment_id for c in constrained] == ["seg_red"]


def test_matcher_writes_results_to_session_state():
    session_id = f"s_{uuid4().hex[:8]}"
    state = AssemblyState(session_id=session_id)
    asset = VideoAsset(filename="e2e_red.mp4", status=AssetStatus.ANALYZED)
    state.assets.append(asset)
    state.analysis_results[asset.asset_id] = AnalysisResult(
        asset_id=asset.asset_id,
        segments=[Segment(asset_id=asset.asset_id, start_time=0, end_time=6,
                          labels=["来源:e2e_red", "色调:红色"])],
        status="completed",
    )
    slot = Slot(position=0, semantic_query="红色开头", min_duration=3.0, max_duration=10.0)
    state.slots.append(slot)
    manager = get_state_manager()
    manager.update_session(state)

    result = MatcherAgent().execute({}, {"session_id": session_id})

    assert result.success is True
    saved = manager.get_session(session_id)
    assert saved.current_phase == "matched"
    best = saved.match_results[slot.slot_id].get_best_candidate()
    assert best is not None and best.overall_score > 0


def test_matcher_fails_without_slots_or_segments():
    session_id = f"s_{uuid4().hex[:8]}"
    manager = get_state_manager()
    manager.create_session(session_id)

    assert "槽位" in MatcherAgent().execute({}, {"session_id": session_id}).message

    state = manager.get_session(session_id)
    state.slots.append(Slot(position=0, semantic_query="红色"))
    manager.update_session(state)

    assert "片段" in MatcherAgent().execute({}, {"session_id": session_id}).message
