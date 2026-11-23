"""Webhook API endpoints — V0.1 占位，事件回调尚未接入。"""

from fastapi import APIRouter

from penclip.api.v1.dependencies import not_implemented

router = APIRouter(prefix="/webhooks", tags=["webhook"])


@router.post("")
async def register_webhook():
    not_implemented("Webhook 注册接口")


@router.delete("/{webhook_id}")
async def delete_webhook(webhook_id: str):
    not_implemented("Webhook 注销接口")
