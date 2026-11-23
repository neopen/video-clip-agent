"""WorkflowOrchestrator — manages linear pipeline workflow execution."""

from typing import Any, Callable, Dict, List

from penclip.logger import debug, info

Handler = Callable[[Dict[str, Any]], Dict[str, Any]]


class WorkflowOrchestrator:
    """Orchestrates the linear clip workflow: upload → sample → parse → analyze → match → compose."""

    def __init__(self):
        self._nodes: Dict[str, Handler] = {}
        self._edges: List[tuple] = []
        debug("WorkflowOrchestrator initialized")

    def add_node(self, name: str, handler: Handler):
        self._nodes[name] = handler

    def add_edge(self, from_node: str, to_node: str):
        self._edges.append((from_node, to_node))

    def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the registered nodes in chain order, stopping at the first failure.

        `failed` names the node that broke the chain so callers can report the
        documented 空缺报告 instead of pretending the run succeeded.
        """
        order = self._execution_order()
        info(f"WorkflowOrchestrator: {len(order)} node(s): {' → '.join(order)}")
        completed: List[str] = []
        for name in order:
            try:
                state = self._nodes[name](state) or state
            except Exception as e:
                info(f"WorkflowOrchestrator: node '{name}' failed: {e}")
                return {"state": state, "completed": completed, "failed": name, "message": str(e)}
            completed.append(name)
        return {
            "state": state,
            "completed": completed,
            "failed": None,
            "message": f"{len(completed)} 个节点执行完成" if completed else "没有可执行的节点",
        }

    def _execution_order(self) -> List[str]:
        if not self._edges:
            return list(self._nodes)
        successors = dict(self._edges)
        downstream = {dst for _, dst in self._edges}
        starts = [name for name in self._nodes if name not in downstream]
        order: List[str] = []
        for start in starts or list(self._nodes[:1]):
            node, visited = start, set()
            while node in self._nodes and node not in visited:
                visited.add(node)
                order.append(node)
                node = successors.get(node)
        return order + [name for name in self._nodes if name not in order]
