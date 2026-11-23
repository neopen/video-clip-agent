"""GraphFactory — builds LangGraph StateGraph instances for different workflows."""

from typing import Any, Callable, Dict

from penclip.core.orchestration.graph_engine import LangGraphEngine
from penclip.core.orchestration.workflow_orchestrator import WorkflowOrchestrator
from penclip.logger import debug

# 线性链路工作流的计算节点；指令解析与规划审核仍由用户在中枢逐条确认
_PIPELINE_INSTRUCTIONS = ("分析素材", "匹配片段", "合成")


class GraphFactory:
    """Factory for creating pre-configured LangGraph state graphs."""

    @staticmethod
    def create_linear_clip_graph() -> Any:
        """Create the standard linear clip workflow graph."""
        debug("GraphFactory: creating linear clip graph (stub)")
        return LangGraphEngine()

    @staticmethod
    def create_hub_graph() -> Any:
        """Create the hub dispatch graph."""
        debug("GraphFactory: creating hub graph (stub)")
        return LangGraphEngine()

    @staticmethod
    def create_linear_workflow(
        hub: Any,
        session_id: str,
        confirm: Callable[[str], bool] = lambda _message: True,
    ) -> WorkflowOrchestrator:
        """Wire the documented linear pipeline (analyze → match → compose) on the hub.

        `confirm` decides high-risk steps: the pipeline never renders without it,
        keeping the human-in-the-loop gate that the linear model is built on.
        """
        workflow = WorkflowOrchestrator()
        previous = None
        for instruction in _PIPELINE_INSTRUCTIONS:
            name = instruction
            workflow.add_node(name, _hub_step(hub, session_id, instruction, confirm))
            if previous:
                workflow.add_edge(previous, name)
            previous = name
        debug(f"GraphFactory: linear workflow built with {len(_PIPELINE_INSTRUCTIONS)} nodes")
        return workflow


def _hub_step(hub: Any, session_id: str, instruction: str,
              confirm: Callable[[str], bool]) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    def handler(state: Dict[str, Any]) -> Dict[str, Any]:
        response = hub.process(instruction, session_id)
        if response.needs_confirmation:
            if not confirm(response.confirmation_message):
                response = hub.cancel(session_id)
            else:
                response = hub.confirm(session_id)
        if not response.success:
            raise RuntimeError(response.message or f"{instruction} 执行失败")
        state.setdefault("steps", []).append({"instruction": instruction, "result": response.data})
        return state

    return handler

