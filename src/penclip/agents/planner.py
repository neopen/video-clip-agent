"""PlannerAgent — creates and modifies timeline blueprints from user intents."""

import json
import os
from typing import Any, Dict, List, Optional

from penclip.agents.base import BaseAgent, ExecutionContext
from penclip.core.state.state_manager import get_state_manager
from penclip.domain.entities.slot import Slot
from penclip.domain.entities.timeline import TimelineBlueprint
from penclip.domain.value_objects.capability import CapabilityDeclaration
from penclip.domain.value_objects.execution_result import ExecutionResult
from penclip.domain.value_objects.intent import IntentType
from penclip.domain.value_objects.risk import RiskLevel
from penclip.logger import info

DEFAULT_CONFIG = {
    "max_slots": 20,
    "default_duration": 5.0,
}

# Timeline edits that V0.1 cannot apply to the session state yet.
_V02_MUTATIONS = {
    IntentType.PLAN_INSERT: "插入槽位",
    IntentType.PLAN_DELETE: "删除槽位",
    IntentType.PLAN_REORDER: "调整顺序",
    IntentType.PLAN_DUPLICATE: "复制槽位",
}


class PlannerAgent(BaseAgent):
    agent_id = "planner"
    agent_name = "PlannerAgent"
    version = "0.1.0"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = {**DEFAULT_CONFIG, **(config or {})}
        super().__init__(config=cfg)

    def declare_capabilities(self) -> CapabilityDeclaration:
        return CapabilityDeclaration(
            name="timeline_planner",
            intents=[
                IntentType.PLAN_CREATE, IntentType.PLAN_APPEND,
                IntentType.PLAN_INSERT, IntentType.PLAN_DELETE,
                IntentType.PLAN_REORDER, IntentType.PLAN_DUPLICATE,
            ],
            description="Creates and modifies timeline blueprints from user instructions",
            input_schema={
                "instruction": {"type": "string", "description": "Natural language instruction"},
            },
            output_schema={
                "timeline": {"type": "object", "description": "TimelineBlueprint"},
            },
            risk_level=RiskLevel.HIGH,
            version=self.version,
            agent_id=self.agent_id,
        )

    def execute(self, params: Dict[str, Any], context: ExecutionContext) -> ExecutionResult:
        intent = self._extract_intent(params, context)
        if intent in _V02_MUTATIONS:
            return ExecutionResult(
                success=False, status="unsupported",
                message=f"{_V02_MUTATIONS[intent]}属于 V0.2 范围，V0.1 仅支持创建与追加时间线",
            )
        instruction = params.get("raw_text", "") or params.get("instruction", "")
        timeline = self._parse_intent(instruction)

        state_manager = get_state_manager()
        state = state_manager.get_session(self._extract_session_id(context) or "")
        if state is None:
            return ExecutionResult(
                success=False, status="failed",
                message="会话状态不存在，无法保存时间线",
            )
        append = intent == IntentType.PLAN_APPEND
        base = len(state.slots) if append else 0
        if append:
            for slot in timeline.slots:
                slot.position = base + slot.position
                state.add_slot(slot)
        else:
            state.slots = timeline.slots
            state.match_results = {}
        state.current_phase = "planned"
        state_manager.update_session(state)

        info(f"PlannerAgent: {'appended' if append else 'planned'} {len(timeline.slots)} slot(s), "
             f"total={len(state.slots)}")
        return ExecutionResult(
            success=True,
            data={"timeline": timeline.model_dump(), "slots": len(state.slots)},
            message=(f"{'追加' if append else '创建'}时间线：{len(timeline.slots)} 个片段槽位，"
                     f"共 {len(state.slots)} 个"),
            suggestions=["下一步：分析素材 → 匹配片段 → 合成（也可用 pipeline 一次跑完）"],
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

    def _parse_intent(self, text: str) -> TimelineBlueprint:
        slots = self._build_slots(text)
        timeline = TimelineBlueprint(slots=slots, total_duration=sum(
            (s.min_duration + s.max_duration) / 2 for s in slots
        ))
        return self._apply_global_context(timeline)

    def _build_slots(self, text: str) -> List[Slot]:
        llm_slots = self._extract_slots_via_llm(text)
        if llm_slots:
            return [
                Slot(
                    position=i,
                    semantic_query=s["query"],
                    min_duration=3.0,
                    max_duration=15.0,
                    transition_type="fade",
                )
                for i, s in enumerate(llm_slots)
            ]
        return self._build_slots_by_keyword(text)

    def _build_slots_by_keyword(self, text: str) -> List[Slot]:
        """V0.1 兜底：逗号切分提取槽位。"""
        segments = text.replace("，", ",").replace("、", ",").split(",")
        slots = []
        for i, seg in enumerate(segments):
            seg = seg.strip()
            if not seg:
                continue
            slots.append(Slot(
                position=i,
                semantic_query=seg,
                min_duration=3.0,
                max_duration=15.0,
                transition_type="fade",
            ))
        return slots

    def _extract_slots_via_llm(self, text: str) -> Optional[List[Dict[str, Any]]]:
        """调用 LLM 解读需求并提取槽位；失败返回 None 回退关键词解析。"""
        try:
            from penclip.llm.client_factory import convert_response, get_ai_client
            from penclip.services.llm_config import resolve_provider_config

            provider = os.environ.get("AI_PROVIDER") or "qwen"
            client = get_ai_client(provider)
            model = resolve_provider_config(provider).model

            messages = [
                {
                    "role": "system",
                    "content": (
                        "你是视频剪辑助手。根据用户需求提取时间线片段槽位，"
                        "返回 JSON 数组，每项含 query（片段描述）与 position（从 0 开始的序号）。"
                        "只输出 JSON，不要输出其他内容。"
                    ),
                },
                {"role": "user", "content": text},
            ]
            response = client.chat.completions.create(
                model=model, messages=messages, temperature=0.1
            )
            content = convert_response(provider, response)
            slots = json.loads(self._strip_markdown(content))
            if isinstance(slots, list):
                return [s for s in slots if isinstance(s, dict) and s.get("query")]
            return None
        except Exception as e:
            info(f"PlannerAgent: LLM 槽位提取不可用，回退关键词解析: {e}")
            return None

    @staticmethod
    def _strip_markdown(content: str) -> str:
        """去除 LLM 输出中的 Markdown 代码块标记，并提取 JSON 部分。"""
        content = content.strip()
        if content.startswith("```"):
            content = "\n".join(content.split("\n")[1:])
        if content.endswith("```"):
            content = "\n".join(content.split("\n")[:-1])
        content = content.strip()
        # 数组优先：截成第一个 { 到最后一个 } 会丢掉外层方括号，导致解析失败
        for opener, closer in (("[", "]"), ("{", "}")):
            start, end = content.find(opener), content.rfind(closer)
            if start != -1 and end > start:
                return content[start:end + 1]
        return content

    def _apply_global_context(self, timeline: TimelineBlueprint) -> TimelineBlueprint:
        return timeline


_planner: PlannerAgent = None


def get_planner_agent() -> PlannerAgent:
    global _planner
    if _planner is None:
        _planner = PlannerAgent()
    return _planner
