"""导出接口测试：V0.1 出片走中枢「合成」意图，导出路由仍为占位。"""

import pytest

STUB_PATHS = [
    ("post", "/api/v1/exports/render"),
    ("get", "/api/v1/exports/export-1/status"),
    ("get", "/api/v1/exports/export-1/download"),
]


@pytest.mark.parametrize("method,path", STUB_PATHS)
def test_export_routes_report_unimplemented(client, method, path):
    resp = getattr(client, method)(path)
    assert resp.status_code == 501
    assert "/api/v1/tasks" in resp.json()["error"]
