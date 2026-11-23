"""Dependency injection — FastAPI dependency providers for hub, state, agents."""

from fastapi import HTTPException

from penclip.core.hub.central_hub import get_hub, CentralHub
from penclip.core.state.state_manager import get_state_manager, StateManager


def get_central_hub() -> CentralHub:
    return get_hub()


def get_state_manager_dep() -> StateManager:
    return get_state_manager()


def not_implemented(feature: str) -> None:
    """资源型路由在 V0.1 只是占位：返回 501，不能用假数据冒充执行成功。"""
    raise HTTPException(
        status_code=501,
        detail=f"{feature}尚未开放，V0.1 请用 POST /api/v1/tasks 提交自然语言指令",
    )
