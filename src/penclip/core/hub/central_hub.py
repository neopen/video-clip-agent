"""CentralHub — the star-hub command dispatch center."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from penclip.core.event.event_bus import get_event_bus
from penclip.core.event.event_types import Event, EventType
from penclip.core.hub.capability_registry import CapabilityRegistry
from penclip.core.hub.context_manager import ContextManager
from penclip.core.hub.intent_recognizer import IntentRecognizer
from penclip.core.hub.risk_assessor import RiskAssessor
from penclip.core.state.state_manager import get_state_manager
from penclip.domain.value_objects.execution_result import ExecutionResult
from penclip.domain.value_objects.intent import IntentType
from penclip.logger import info, warning


@dataclass
class HubRequest:
    user_input: str
    session_id: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HubResponse:
    success: bool
    intent: Optional[IntentType] = None
    message: str = ""
    data: Optional[Dict[str, Any]] = None
    suggestions: List[str] = field(default_factory=list)
    needs_confirmation: bool = False
    confirmation_message: str = ""
    needs_clarification: bool = False
    clarification: str = ""


@dataclass
class PendingOperation:
    session_id: str
    intent: IntentType
    params: Dict[str, Any]
    capability: Any
    agent: Any


# Intents that only read state; snapshotting them would pollute the undo stack.
_NON_MUTATING_INTENTS = frozenset({
    IntentType.STATE_QUERY_PROGRESS.value,
    IntentType.STATE_QUERY_CAPABILITIES.value,
    IntentType.STATE_UNDO.value,
    IntentType.STATE_REDO.value,
    IntentType.UNKNOWN.value,
})


class CentralHub:
    def __init__(self):
        self.registry = CapabilityRegistry()
        self.intent_recognizer = IntentRecognizer()
        self.risk_assessor = RiskAssessor()
        self.context_manager = ContextManager()
        self.state_manager = get_state_manager()
        self.event_bus = get_event_bus()
        self._agents: Dict[str, Any] = {}
        self._pending: Dict[str, PendingOperation] = {}
        info("CentralHub initialized")

    def process(self, user_input: str, session_id: Optional[str] = None) -> HubResponse:
        session_id = self._ensure_session(session_id)
        self.context_manager.get_context(session_id)

        # 1. Intent recognition
        intent_result = self.intent_recognizer.recognize(user_input)
        params = {**(intent_result.params or {}), "intent": intent_result.intent.value}
        self.event_bus.publish(Event(
            event_type=EventType.INTENT_RECOGNIZED,
            session_id=session_id,
            data={"intent": intent_result.intent.value},
        ))

        # 2. Context update
        self.context_manager.add_history(session_id, {
            "role": "user", "content": user_input,
            "intent": intent_result.intent.value,
        })

        # 3. Clarification check (单字符输入 或 未匹配到关键词)
        if self.intent_recognizer.needs_clarification(user_input) or intent_result.confidence < 1.0:
            return HubResponse(
                success=False,
                intent=intent_result.intent,
                needs_clarification=True,
                clarification=self.intent_recognizer.generate_clarification(user_input),
            )

        # 4. Risk assessment
        risk = self.risk_assessor.assess(intent_result.intent)
        needs_confirmation = self.risk_assessor.needs_confirmation(risk)

        # 5. Route to capability
        capabilities = self.registry.find_by_intent(intent_result.intent)
        if not capabilities:
            return HubResponse(
                success=False,
                intent=intent_result.intent,
                message=f"No capability registered for intent: {intent_result.intent.value}",
            )
        cap = capabilities[0]
        agent = self._agents.get(cap.agent_id) if cap.agent_id else None

        # 6. High-risk gate: wait for confirmation before executing
        if needs_confirmation:
            self._pending[session_id] = PendingOperation(
                session_id=session_id,
                intent=intent_result.intent,
                params=params,
                capability=cap,
                agent=agent,
            )
            return HubResponse(
                success=True,
                intent=intent_result.intent,
                message="等待确认",
                needs_confirmation=True,
                confirmation_message=self.risk_assessor.generate_confirmation_message(intent_result.intent),
            )

        # 7. Execute capability
        return self._to_response(intent_result.intent, self._execute(
            agent, cap, params, session_id, user_input))

    @staticmethod
    def _to_response(intent: IntentType, result: ExecutionResult) -> HubResponse:
        return HubResponse(
            success=result.success,
            intent=intent,
            message=result.message,
            data=result.data,
            suggestions=list(result.suggestions or []),
        )

    def _execute(self, agent: Any, cap: Any, params: Dict[str, Any], session_id: str,
                 label: str = "") -> ExecutionResult:
        if agent is None:
            return ExecutionResult(success=True, message=f"Capability '{cap.name}' executed (no agent attached)")
        pushed = self._snapshot_for_undo(session_id, params.get("intent") or cap.name, label)
        context = {"session_id": session_id, "intent": params.get("intent")}
        result = agent.execute(params, context)
        if pushed and not result.success:
            # 没改变状态的失败不该留在撤销栈里，否则「撤销」会回退一次空操作
            self._drop_undo_snapshot(session_id)
        return result

    def _ensure_session(self, session_id: Optional[str]) -> str:
        """Create the session state on first use so progress/undo always have a target."""
        if session_id is None:
            state = self.state_manager.create_session()
            return state.session_id
        if self.state_manager.get_session(session_id) is None:
            self.state_manager.create_session(session_id)
        return session_id

    def _snapshot_for_undo(self, session_id: str, operation: str, label: str = "") -> bool:
        """记录变更前状态；`label` 用用户原话，撤销提示才读得懂（如「匹配片段」而非 execute）。"""
        if operation in _NON_MUTATING_INTENTS:
            return False
        state = self.state_manager.get_session(session_id)
        if state is None:
            return False
        state.snapshot_for_undo((label or operation).strip()[:40])
        self.state_manager.update_session(state)
        return True

    def _drop_undo_snapshot(self, session_id: str) -> None:
        state = self.state_manager.get_session(session_id)
        if state is None or not state.interaction_context.undo_stack:
            return
        state.interaction_context.undo_stack.pop()
        self.state_manager.update_session(state)

    def confirm(self, session_id: str) -> HubResponse:
        pending = self._pending.pop(session_id, None)
        if pending is None:
            return HubResponse(success=False, message="没有待确认的操作")
        return self._to_response(pending.intent, self._execute(
            pending.agent, pending.capability, pending.params, pending.session_id,
            pending.params.get("raw_text", "")))

    def cancel(self, session_id: str) -> HubResponse:
        pending = self._pending.pop(session_id, None)
        if pending is None:
            return HubResponse(success=False, message="没有待确认的操作")
        return HubResponse(success=True, intent=pending.intent, message=f"已取消 {pending.intent.value}")

    def register_agent(self, agent: Any) -> bool:
        """Register an agent and its capabilities with the hub."""
        try:
            declaration = agent.declare_capabilities()
            declaration.agent_id = agent.agent_id
            self._agents[agent.agent_id] = agent
            self.registry.register(declaration)
            self.event_bus.publish(Event(
                event_type=EventType.CAPABILITY_REGISTERED,
                data={"agent_id": agent.agent_id, "capability": declaration.name},
            ))
            info(f"CentralHub: agent '{agent.agent_id}' registered")
            return True
        except Exception as e:
            warning(f"CentralHub: failed to register agent: {e}")
            return False

    def unregister_agent(self, agent_id: str) -> bool:
        agent = self._agents.pop(agent_id, None)
        if agent is None:
            return False
        self.registry.unregister(agent.declare_capabilities().name)
        return True

    def get_capabilities(self) -> List[Any]:
        return self.registry.list_all()

    def handle_interrupt(self, session_id: str, user_input: str) -> HubResponse:
        """Resume from an interrupt (e.g., user confirmation)."""
        text = user_input.strip().lower()
        if text in ("y", "yes", "确认", "是"):
            return self.confirm(session_id)
        if text in ("n", "no", "取消", "否"):
            return self.cancel(session_id)
        return self.process(user_input, session_id=session_id)


_hub: CentralHub = None


def get_hub() -> CentralHub:
    global _hub
    if _hub is None:
        _hub = CentralHub()
    return _hub
