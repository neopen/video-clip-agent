"""Timeline API endpoints — V0.1 占位，时间线由 PlannerAgent 写入会话状态。"""

from fastapi import APIRouter

from penclip.api.v1.dependencies import not_implemented

router = APIRouter(prefix="/timelines", tags=["timeline"])


@router.post("")
async def create_timeline():
    not_implemented("时间线创建接口")


@router.get("/{timeline_id}")
async def get_timeline(timeline_id: str):
    not_implemented("时间线查询接口")


@router.put("/{timeline_id}/slots/{slot_id}")
async def update_slot(timeline_id: str, slot_id: str):
    not_implemented("槽位编辑接口")
