"""Asset API endpoints — V0.1 占位，素材登记走中枢的 ASSET_ADD 意图。"""

from fastapi import APIRouter

from penclip.api.v1.dependencies import not_implemented

router = APIRouter(prefix="/assets", tags=["asset"])


@router.post("")
async def upload_asset():
    not_implemented("素材上传接口")


@router.get("/{asset_id}")
async def get_asset(asset_id: str):
    not_implemented("素材查询接口")


@router.get("/{asset_id}/metadata")
async def get_asset_metadata(asset_id: str):
    not_implemented("素材元数据接口")


@router.post("/{asset_id}/analyze")
async def analyze_asset(asset_id: str):
    not_implemented("单素材分析接口")
