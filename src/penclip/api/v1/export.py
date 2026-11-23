"""Export API endpoints — V0.1 占位，出片请用「合成」指令 + 确认门。"""

from fastapi import APIRouter

from penclip.api.v1.dependencies import not_implemented

router = APIRouter(prefix="/exports", tags=["export"])


@router.post("/render")
async def start_render():
    not_implemented("渲染提交接口")


@router.get("/{task_id}/status")
async def get_render_status(task_id: str):
    not_implemented("渲染状态接口")


@router.get("/{task_id}/download")
async def download_video(task_id: str):
    not_implemented("成片下载接口")
