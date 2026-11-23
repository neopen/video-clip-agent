"""StateAgent — answers session progress queries and drives undo/redo over AssemblyState."""

from typing import Any, Dict, Optional

from penclip.agents.base import BaseAgent, ExecutionContext
from penclip.core.state.state_manager import get_state_manager
from penclip.domain.value_objects.capability import CapabilityDeclaration
from penclip.domain.value_objects.execution_result import ExecutionResult
from penclip.domain.value_objects.intent import IntentType
from penclip.domain.value_objects.risk import RiskLevel
from penclip.logger import info

DEFAULT_CONFIG = {
    "undo_limit": 10,
}


class StateAgent(BaseAgent):
    agent_id = "state_manager"
    agent_name = "StateAgent"
    version = "0.1.0"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = {**DEFAULT_CONFIG, **(config or {})}
        super().__init__(config=cfg)

    def declare_capabilities(self) -> CapabilityDeclaration:
        return CapabilityDeclaration(
            name="session_state",
            intents=[
                IntentType.STATE_QUERY_PROGRESS, IntentType.STATE_QUERY_CAPABILITIES,
                IntentType.STATE_UNDO, IntentType.STATE_REDO,
            ],
            description="Reports assembly progress and replays undo/redo on session state",
            input_schema={
                "intent": {"type": "string", "description": "Recognised intent value"},
            },
            output_schema={
                "progress": {"type": "object", "description": "Session progress summary"},
            },
            risk_level=RiskLevel.LOW,
            version=self.version,
            agent_id=self.agent_id,
        )

    def execute(self, params: Dict[str, Any], context: ExecutionContext) -> ExecutionResult:
        intent = self._extract_intent(params, context)
        if intent == IntentType.STATE_QUERY_CAPABILITIES:
            return self._list_capabilities()

        state_manager = get_state_manager()
        state = state_manager.get_session(self._extract_session_id(context) or "")
        if state is None:
            return ExecutionResult(
                success=False, message="会话不存在或尚无操作记录", status="failed",
            )

        if intent == IntentType.STATE_UNDO:
            return self._undo(state, state_manager)
        if intent == IntentType.STATE_REDO:
            return self._redo(state, state_manager)
        return self._progress(state)

    @staticmethod
    def _progress(state: Any) -> ExecutionResult:
        segments = sum(len(a.segments) for a in state.analysis_results.values())
        matched = sum(1 for m in state.match_results.values() if m.candidates)
        progress = {
            "session_id": state.session_id,
            "phase": state.current_phase,
            "assets": len(state.assets),
            "analyzed_assets": len(state.analysis_results),
            "segments": segments,
            "slots": len(state.slots),
            "matched_slots": matched,
            "undo_depth": len(state.interaction_context.undo_stack),
        }
        info(f"StateAgent: progress phase={state.current_phase} assets={progress['assets']}")
        return ExecutionResult(
            success=True,
            data=progress,
            message=(
                f"阶段：{state.current_phase}｜素材 {progress['assets']} 个"
                f"（已分析 {progress['analyzed_assets']}）｜片段 {segments}"
                f"｜槽位 {progress['slots']}（已匹配 {matched}）"
            ),
        )

    @staticmethod
    def _list_capabilities() -> ExecutionResult:
        from penclip.hub.hub_core import get_hub

        capabilities = [
            {
                "name": cap.name,
                "agent_id": cap.agent_id,
                "intents": [i.value for i in cap.intents],
                "risk_level": getattr(cap.risk_level, "value", str(cap.risk_level)),
            }
            for cap in get_hub().registry.list_all()
        ]
        return ExecutionResult(
            success=True,
            data={"capabilities": capabilities},
            message=f"已注册 {len(capabilities)} 个能力",
        )

    def _undo(self, state: Any, state_manager: Any) -> ExecutionResult:
        stack = state.interaction_context.undo_stack
        if not stack:
            return ExecutionResult(
                success=False, message="没有可撤销的操作", status="failed",
                suggestions=[f"可重做 {len(state.interaction_context.redo_stack)} 步"],
            )
        # 先把撤销前的状态压入 redo 栈，再回退；否则 redo 只会重放已回退的状态
        operation = stack[-1]["operation"]
        state.push_redo_snapshot(operation, int(self._config["undo_limit"]))
        entry = state.pop_undo_snapshot()
        state_manager.update_session(state)
        info(f"StateAgent: undone '{entry['operation']}'")
        return ExecutionResult(
            success=True,
            data={"undone": entry["operation"], "phase": state.current_phase},
            message=f"已撤销：{entry['operation']}",
        )

    def _redo(self, state: Any, state_manager: Any) -> ExecutionResult:
        if not state.interaction_context.redo_stack:
            return ExecutionResult(success=False, message="没有可重做的操作", status="failed")
        entry = state.interaction_context.redo_stack.pop()
        limit = int(self._config["undo_limit"])
        state.snapshot_for_undo(f"redo:{entry['operation']}", limit)
        state.restore_from(entry["state"])
        state_manager.update_session(state)
        return ExecutionResult(
            success=True,
            data={"redone": entry["operation"], "phase": state.current_phase},
            message=f"已重做：{entry['operation']}",
        )

    @staticmethod
    def _extract_intent(params: Dict[str, Any], context: Any) -> Optional[IntentType]:
        raw = params.get("intent")
        if raw is None and isinstance(context, ExecutionContext):
            raw = context.intent
        if isinstance(raw, IntentType):
            return raw
        return next((i for i in IntentType if i.value == raw), None)

    @staticmethod
    def _extract_session_id(context: Any) -> Optional[str]:
        if isinstance(context, dict):
            return context.get("session_id")
        if isinstance(context, ExecutionContext):
            return context.session_id
        return None
