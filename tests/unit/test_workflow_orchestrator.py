"""WorkflowOrchestrator 与线性链路工作流单元测试。"""

from penclip.core.hub.central_hub import HubResponse
from penclip.core.orchestration.graph_factory import GraphFactory
from penclip.core.orchestration.workflow_orchestrator import WorkflowOrchestrator


def _node(name, trace, fail=None):
    def handler(state):
        trace.append(name)
        if fail:
            raise RuntimeError(fail)
        state.setdefault("visited", []).append(name)
        return state

    return handler


def test_run_follows_declared_edges():
    trace = []
    wf = WorkflowOrchestrator()
    wf.add_node("match", _node("match", trace))
    wf.add_node("compose", _node("compose", trace))
    wf.add_node("analyze", _node("analyze", trace))
    wf.add_edge("analyze", "match")
    wf.add_edge("match", "compose")

    result = wf.run({})

    assert result["failed"] is None
    assert trace == ["analyze", "match", "compose"]
    assert result["state"]["visited"] == ["analyze", "match", "compose"]


def test_run_without_edges_uses_insertion_order():
    trace = []
    wf = WorkflowOrchestrator()
    wf.add_node("a", _node("a", trace))
    wf.add_node("b", _node("b", trace))

    wf.run({})

    assert trace == ["a", "b"]


def test_run_stops_at_failing_node():
    trace = []
    wf = WorkflowOrchestrator()
    wf.add_node("analyze", _node("analyze", trace, fail="没有可分析的素材"))
    wf.add_node("match", _node("match", trace))
    wf.add_edge("analyze", "match")

    result = wf.run({})

    assert result["completed"] == []
    assert result["failed"] == "analyze"
    assert "没有可分析的素材" in result["message"]
    assert trace == ["analyze"]


def test_run_without_nodes_reports_empty_run():
    result = WorkflowOrchestrator().run({"session_id": "s1"})

    assert result["failed"] is None
    assert result["state"] == {"session_id": "s1"}
    assert "没有可执行" in result["message"]


class _FakeHub:
    """最小中枢替身：只有 合成 是高风险，可选让某一步失败。"""

    def __init__(self, fail_on=None):
        self.calls = []
        self.confirmed = False
        self._fail_on = fail_on

    def process(self, user_input, session_id=None):
        self.calls.append(user_input)
        if user_input == "合成":
            return HubResponse(success=True, message="等待确认", needs_confirmation=True,
                               confirmation_message="确认开始最终渲染？")
        if user_input == self._fail_on:
            return HubResponse(success=False, message=f"{user_input} 失败：上游产物缺失")
        return HubResponse(success=True, message=f"{user_input} 完成", data={"ok": True})

    def confirm(self, session_id):
        self.confirmed = True
        return HubResponse(success=True, message="已合成", data={"output_path": "out.mp4"})

    def cancel(self, session_id):
        return HubResponse(success=False, message="已取消 合成")


def test_linear_workflow_runs_all_pipeline_nodes():
    hub = _FakeHub()
    wf = GraphFactory.create_linear_workflow(hub, "s1", confirm=lambda _msg: True)

    result = wf.run({"session_id": "s1"})

    assert result["completed"] == ["分析素材", "匹配片段", "合成"]
    assert hub.confirmed is True
    assert [step["instruction"] for step in result["state"]["steps"]] == result["completed"]


def test_linear_workflow_respects_render_gate():
    hub = _FakeHub()
    wf = GraphFactory.create_linear_workflow(hub, "s1", confirm=lambda _msg: False)

    result = wf.run({"session_id": "s1"})

    assert hub.confirmed is False
    assert result["completed"] == ["分析素材", "匹配片段"]
    assert result["failed"] == "合成"


def test_linear_workflow_breaks_on_missing_asset():
    hub = _FakeHub(fail_on="分析素材")
    wf = GraphFactory.create_linear_workflow(hub, "s1")

    result = wf.run({"session_id": "s1"})

    assert result["failed"] == "分析素材"
    assert hub.calls == ["分析素材"]
