"""AssemblyState 撤销/重做单元测试 —— 快照回滚需保持实体类型与双栈完整。"""

from uuid import uuid4

from penclip.agents.state_agent import StateAgent
from penclip.core.state.state_manager import get_state_manager
from penclip.domain.entities.assembly_state import AnalysisResult, AssemblyState
from penclip.domain.entities.segment import Segment
from penclip.domain.entities.slot import Slot
from penclip.domain.entities.video_asset import AssetStatus, VideoAsset


def _state() -> AssemblyState:
    state = AssemblyState(session_id=f"s_{uuid4().hex[:8]}")
    asset = VideoAsset(filename="a.mp4", status=AssetStatus.ANALYZED)
    state.assets.append(asset)
    state.slots.append(Slot(position=0, semantic_query="红色开头"))
    state.analysis_results[asset.asset_id] = AnalysisResult(
        asset_id=asset.asset_id,
        segments=[Segment(asset_id=asset.asset_id, start_time=0, end_time=5,
                          labels=["色调:红色"])],
        status="completed",
    )
    return state


def test_restore_keeps_nested_pydantic_types():
    state = _state()
    state.snapshot_for_undo("asset_add")
    state.assets.append(VideoAsset(filename="b.mp4"))

    state.pop_undo_snapshot()

    assert len(state.assets) == 1
    assert isinstance(state.assets[0], VideoAsset)
    assert isinstance(state.slots[0], Slot)
    segments = next(iter(state.analysis_results.values())).segments
    assert isinstance(segments[0], Segment) and segments[0].labels == ["色调:红色"]


def test_undo_then_redo_round_trips():
    state = _state()
    state.snapshot_for_undo("asset_add")
    before = len(state.assets)
    state.assets.append(VideoAsset(filename="b.mp4"))

    # 顺序即契约：先记录 redo（撤销前的状态），再回退
    state.push_redo_snapshot("asset_add")
    entry = state.pop_undo_snapshot()
    assert entry["operation"] == "asset_add"
    assert len(state.assets) == before

    redo = state.interaction_context.redo_stack.pop()
    state.snapshot_for_undo(f"redo:{redo['operation']}")
    state.restore_from(redo["state"])
    assert len(state.assets) == before + 1


def test_undo_stack_is_bounded():
    state = _state()

    for i in range(15):
        state.snapshot_for_undo(f"op_{i}", limit=10)

    stack = state.interaction_context.undo_stack
    assert len(stack) == 10
    assert stack[0]["operation"] == "op_5"


def _run_agent(state: AssemblyState, intent: str):
    manager = get_state_manager()
    manager.update_session(state)
    agent = StateAgent()
    result = agent.execute({"intent": intent}, {"session_id": state.session_id})
    return result, manager.get_session(state.session_id)


def test_state_agent_reports_progress():
    state = _state()

    result, _ = _run_agent(state, "state_query_progress")

    assert result.success is True
    assert result.data["phase"] == "idle"
    assert result.data["assets"] == 1
    assert result.data["segments"] == 1
    assert result.data["slots"] == 1


def test_state_agent_undo_restores_previous_phase():
    state = _state()
    state.snapshot_for_undo("analyze_full")
    state.current_phase = "analyzed"
    state.assets.append(VideoAsset(filename="b.mp4"))

    result, restored = _run_agent(state, "state_undo")

    assert result.success is True
    assert restored.current_phase == "idle"
    assert len(restored.assets) == 1
    assert restored.interaction_context.redo_stack[-1]["operation"] == "analyze_full"


def test_state_agent_redo_reapplies_undone_state():
    state = _state()
    state.snapshot_for_undo("analyze_full")
    state.assets.append(VideoAsset(filename="b.mp4"))
    manager = get_state_manager()
    manager.update_session(state)
    StateAgent().execute({"intent": "state_undo"}, {"session_id": state.session_id})

    result, redone = _run_agent(manager.get_session(state.session_id), "state_redo")

    assert result.success is True
    assert len(redone.assets) == 2


def test_state_agent_undo_without_history_fails():
    state = AssemblyState(session_id=f"s_{uuid4().hex[:8]}")

    result, _ = _run_agent(state, "state_undo")

    assert result.success is False
    assert "没有可撤销" in result.message
