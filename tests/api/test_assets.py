"""素材接口测试：V0.1 为占位路由，必须明确拒绝而不是假成功。"""

import pytest

STUB_PATHS = [
    ("post", "/api/v1/assets"),
    ("get", "/api/v1/assets/asset-1"),
    ("get", "/api/v1/assets/asset-1/metadata"),
    ("post", "/api/v1/assets/asset-1/analyze"),
]


@pytest.mark.parametrize("method,path", STUB_PATHS)
def test_asset_routes_report_unimplemented(client, method, path):
    resp = getattr(client, method)(path)
    assert resp.status_code == 501
    assert "/api/v1/tasks" in resp.json()["error"]
