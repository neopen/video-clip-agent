"""Webhook 接口测试：V0.1 尚未接入事件回调。"""

import pytest

STUB_PATHS = [
    ("post", "/api/v1/webhooks"),
    ("delete", "/api/v1/webhooks/hook-1"),
]


@pytest.mark.parametrize("method,path", STUB_PATHS)
def test_webhook_routes_report_unimplemented(client, method, path):
    resp = getattr(client, method)(path)
    assert resp.status_code == 501
    assert "/api/v1/tasks" in resp.json()["error"]
