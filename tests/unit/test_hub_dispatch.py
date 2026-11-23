"""CentralHub 分发单元测试 —— 意图注入、会话兜底、撤销快照。"""

from uuid import uuid4

from penclip.agents import register_core_agents
from penclip.agents.base import BaseAgent
from penclip.core.hub.central_hub import CentralHub
from penclip.core.state.state_manager import get_state_manager
from penclip.domain.value_objects.capability import CapabilityDeclaration
from penclip.domain.value_objects.execution_result import ExecutionResult
from penclip.domain.value_objects.intent import IntentType
from penclip.domain.value_objects.risk import RiskLevel


class CapturingAgent(BaseAgent):
    """记录型 agent：捕获中枢传入的 params/context，并修改会话状态。"""

    agent_id = "capture"
    agent_name = "CapturingAgent"

    def __init__(self, intent: IntentType = IntentType.EXECUTE):
        super().__init__()
        self._intent = intent
        self.calls = []

    def declare_capabilities(self) -> CapabilityDeclaration:
        return CapabilityDeclaration(
            name=f"capture_{self._intent.value}",
            intents=[self._intent],
            risk_level=RiskLevel.LOW,
        )

    def execute(self, params, context) -> ExecutionResult:
        self.calls.append((params, context))
        manager = get_state_manager()
        state = manager.get_session(context["session_id"])
        state.current_phase = "captured"
        manager.update_session(state)
        return ExecutionResult(success=True, message="已执行", suggestions=["下一步：合成"])


def _hub():
    hub = CentralHub()
    agent = CapturingAgent()
    hub.register_agent(agent)
    return hub, agent


class FailingAgent(CapturingAgent):
    """执行失败且不改动状态：中枢不应为它留下撤销记录。"""

    def execute(self, params, context) -> ExecutionResult:
        self.calls.append((params, context))
        return ExecutionResult(success=False, message="没有可匹配的片段", status="failed")


def test_hub_injects_recognised_intent_into_params():
    hub, agent = _hub()

    hub.process("匹配片段", f"s_{uuid4().hex[:8]}")

    params, context = agent.calls[0]
    assert params["intent"] == IntentType.EXECUTE.value
    assert context["intent"] == IntentType.EXECUTE.value


def test_hub_passes_agent_suggestions_to_response():
    hub, _ = _hub()

    resp = hub.process("匹配片段", f"s_{uuid4().hex[:8]}")

    assert resp.suggestions == ["下一步：合成"]


def test_hub_snapshots_state_before_mutating_execution():
    hub, _ = _hub()
    session_id = f"s_{uuid4().hex[:8]}"

    hub.process("匹配片段", session_id)

    state = get_state_manager().get_session(session_id)
    assert state.current_phase == "captured"
    snapshot = state.interaction_context.undo_stack[-1]
    # 撤销记录用用户原话做标签，比 execute 这种意图码更可读
    assert snapshot["operation"] == "匹配片段"
    assert snapshot["state"]["current_phase"] == "idle"


def test_read_only_intent_skips_undo_snapshot():
    hub = CentralHub()
    register_core_agents(hub)
    session_id = f"s_{uuid4().hex[:8]}"
    get_state_manager().create_session(session_id)

    resp = hub.process("查看进度", session_id)

    assert resp.success is True
    state = get_state_manager().get_session(session_id)
    assert state.interaction_context.undo_stack == []


def test_failed_execution_leaves_no_undo_snapshot():
    hub = CentralHub()
    hub.register_agent(FailingAgent(IntentType.EXECUTE))
    session_id = f"s_{uuid4().hex[:8]}"

    resp = hub.process("匹配片段", session_id)

    assert resp.success is False
    state = get_state_manager().get_session(session_id)
    assert state.interaction_context.undo_stack == []


def test_hub_creates_missing_session():
    hub, _ = _hub()
    session_id = f"s_{uuid4().hex[:8]}"

    hub.process("匹配片段", session_id)

    assert get_state_manager().get_session(session_id) is not None


def test_generated_session_ids_are_unique():
    hub, agent = _hub()

    hub.process("匹配片段")
    hub.process("匹配片段")

    ids = [context["session_id"] for _, context in agent.calls]
    assert all(sid.startswith("sess_") for sid in ids)
    assert len(set(ids)) == 2
