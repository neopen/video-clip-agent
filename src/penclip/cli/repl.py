"""Interactive REPL loop — the primary human-in-the-loop console."""

from typing import Any, Callable

from penclip.cli.renderer import render_response
from penclip.core.hub.central_hub import CentralHub
from penclip.core.orchestration.graph_factory import GraphFactory
from penclip.core.state.state_manager import StateManager, get_state_manager
from penclip.logger import info

HELP_TEXT = (
    "可用命令：\n"
    "  help           显示本帮助\n"
    "  capabilities   列出已注册能力\n"
    "  status         查看当前进度（阶段/素材/片段/槽位）\n"
    "  pipeline       一键跑完 分析→匹配→合成（渲染前仍会要求确认）\n"
    "  exit / quit    退出\n"
    "\n"
    "V0.1 出片流程（按顺序输入）：\n"
    "  1. 本地视频文件路径            （登记素材；URL 只登记、不下载）\n"
    "  2. \"做个旅行Vlog，风景放开头\"  （全局规划，需确认）\n"
    "  3. \"分析素材\"                  （场景检测 + 打标签）\n"
    "  4. \"匹配片段\"                  （按标签为槽位选段）\n"
    "  5. \"合成\" 或 \"渲染\"            （高风险，需确认）\n"
    "\n"
    "辅助指令：\"进度\" 查看状态，\"撤销\" / \"重做\" 回退操作"
)

_EXIT_KEYWORDS = ("exit", "quit", "退出")
_CONFIRM_KEYWORDS = ("y", "yes", "确认", "是")


def run_repl(
    hub: CentralHub,
    session_id: str,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[..., Any] = print,
) -> None:
    print_fn(f"PenClip 交互控制台 — session: {session_id}")
    info("==================================================================")
    info("<                   欢迎使用  视频混剪智能体 PenClip                >")
    info("<           ⭐https://github.com/neopen/video-clip-agent        >")
    info("==================================================================")
    state_manager = get_state_manager()
    if state_manager.get_session(session_id) is None:
        state_manager.create_session(session_id)
    _print_guidance(state_manager, session_id, print_fn)

    while True:
        try:
            raw = input_fn("penclip> ")
        except (EOFError, KeyboardInterrupt):
            print_fn()
            break

        line = raw.strip()
        if not line:
            continue

        lowered = line.lower()
        if lowered in _EXIT_KEYWORDS:
            break
        if lowered in ("help", "帮助"):
            print_fn(HELP_TEXT)
            continue
        if lowered in ("capabilities", "能力", "能做什么", "功能"):
            _print_capabilities(hub, print_fn)
            continue
        if lowered in ("status", "状态", "进度"):
            render_response(hub.process("查看进度", session_id), print_fn=print_fn)
            continue
        if lowered in ("pipeline", "一键出片"):
            _run_pipeline(hub, session_id, input_fn, print_fn)
            continue

        response = hub.process(line, session_id)

        if response.needs_clarification:
            print_fn(response.clarification)
            continue

        if response.needs_confirmation:
            print_fn(response.confirmation_message)
            answer = input_fn("确认执行? [y/N] ").strip().lower()
            if answer in _CONFIRM_KEYWORDS:
                response = hub.confirm(session_id)
            else:
                response = hub.cancel(session_id)

        render_response(response, print_fn=print_fn)


def _run_pipeline(
    hub: CentralHub,
    session_id: str,
    input_fn: Callable[[str], str],
    print_fn: Callable[..., Any],
) -> None:
    """One-shot linear workflow (analyze → match → compose) with the render gate kept."""
    workflow = GraphFactory.create_linear_workflow(
        hub,
        session_id,
        confirm=lambda message: input_fn(f"{message} [y/N] ").strip().lower() in _CONFIRM_KEYWORDS,
    )
    result = workflow.run({"session_id": session_id})
    for step in result["state"].get("steps", []):
        print_fn(f"  完成：{step['instruction']}")
    if result["failed"]:
        print_fn(f"流程在「{result['failed']}」中断：{result['message']}")
    else:
        print_fn(result["message"])


def _print_capabilities(hub: CentralHub, print_fn: Callable[..., Any]) -> None:
    caps = hub.get_capabilities()
    if not caps:
        print_fn("暂无已注册能力")
        return
    print_fn(f"{len(caps)} 个能力已注册：")
    for cap in caps:
        print_fn(f"  - {cap.name}")


def _has_assets(state_manager: StateManager, session_id: str) -> bool:
    state = state_manager.get_session(session_id)
    return bool(state and state.assets)


def _print_guidance(
    state_manager: StateManager,
    session_id: str,
    print_fn: Callable[..., Any],
) -> None:
    if _has_assets(state_manager, session_id):
        print_fn("已加载资源，可输入指令开始（help 查看命令，exit 退出）。")
    else:
        print_fn("先提供本地视频素材路径（V0.1 不下载 URL），再依次 规划 → 分析 → 匹配 → 合成"
                 "（help 查看完整流程，exit 退出）。")
