"""Session API endpoints — create, inspect and close assembly sessions.

会话是 /api/v1/tasks 与确认—续跑通道的工作对象，因此这里提供真实的生命周期管理。
"""

from typing import Optional

from fastapi import APIRouter, HTTPException

from penclip.api.schemas.request import SessionCreateSchema
from penclip.api.v1.dependencies import get_state_manager_dep

router = APIRouter(prefix="/sessions", tags=["session"])


@router.post("")
def create_session(payload: Optional[SessionCreateSchema] = None):
    """新建装配会话；客户端拿到 session_id 后再提交指令与确认。"""
    manager = get_state_manager_dep()
    session_id = (payload.session_id if payload else None) or None
    if session_id and manager.get_session(session_id) is not None:
        raise HTTPException(status_code=409, detail=f"会话已存在: {session_id}")
    state = manager.create_session(session_id)
    return {"session_id": state.session_id, "phase": state.current_phase}


@router.get("/{session_id}")
def get_session(session_id: str):
    """查看会话概览，等价于 CLI 的「查看进度」。"""
    state = get_state_manager_dep().get_session(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    return {
        "session_id": state.session_id,
        "phase": state.current_phase,
        "assets": len(state.assets),
        "slots": len(state.slots),
        "analyzed": len(state.analysis_results),
        "matched_slots": len(state.match_results),
        "undo_depth": len(state.interaction_context.undo_stack),
    }


@router.delete("/{session_id}")
def delete_session(session_id: str):
    """关闭并清除会话状态。"""
    if not get_state_manager_dep().delete_session(session_id):
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    return {"session_id": session_id, "status": "deleted"}
