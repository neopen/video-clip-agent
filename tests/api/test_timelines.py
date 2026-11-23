"""时间线接口测试：V0.1 由 PlannerAgent 写入会话，资源型路由仍为占位。"""

import pytest

STUB_PATHS = [
    ("post", "/api/v1/timelines"),
    ("get", "/api/v1/timelines/tl-1"),
    ("put", "/api/v1/timelines/tl-1/slots/slot-1"),
]


@pytest.mark.parametrize("method,path", STUB_PATHS)
def test_timeline_routes_report_unimplemented(client, method, path):
    resp = getattr(client, method)(path)
    assert resp.status_code == 501
    assert "/api/v1/tasks" in resp.json()["error"]
