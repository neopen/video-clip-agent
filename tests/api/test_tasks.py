"""任务接口测试：提交 / 状态 / 结果 / 取消 / 确认续跑。"""

import time

PLAN_TEXT = "做个混剪：红色开头，绿色中间，蓝色结尾"


def _wait_result(client, task_id, attempts=50):
    for _ in range(attempts):
        body = client.get(f"/api/v1/tasks/{task_id}/result")
        assert body.status_code == 200
        result = body.json()
        if result.get("status") in ("success", "failed", "cancelled"):
            return result
        time.sleep(0.1)
    raise AssertionError(f"任务 {task_id} 未在预期时间内结束")


def _submit(client, user_input, session_id):
    resp = client.post("/api/v1/tasks", json={"user_input": user_input, "session_id": session_id})
    assert resp.status_code == 200
    return _wait_result(client, resp.json()["task_id"])


def test_submit_task(client):
    resp = client.post("/api/v1/tasks", json={"user_input": "剪掉开头3秒"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["task_id"]
    assert body["session_id"]
    assert body["status"] == "pending"


def test_submit_task_requires_input(client):
    resp = client.post("/api/v1/tasks", json={})
    assert resp.status_code == 422


def test_nonexistent_task_404(client):
    assert client.get("/api/v1/tasks/does-not-exist").status_code == 404
    assert client.get("/api/v1/tasks/does-not-exist/result").status_code == 404
    assert client.delete("/api/v1/tasks/does-not-exist").status_code == 404


def test_task_completes(client):
    resp = client.post("/api/v1/tasks", json={"user_input": "剪掉开头3秒"})
    task_id = resp.json()["task_id"]

    result = _wait_result(client, task_id)
    assert result["task_id"] == task_id
    assert result["status"] == "success"

    status = client.get(f"/api/v1/tasks/{task_id}")
    assert status.status_code == 200
    assert status.json()["task_id"] == task_id


def test_high_risk_task_resumes_after_confirmation(client):
    """确认门：提交只拿到 needs_confirmation，POST confirm 之后才真正写入槽位。"""
    session_id = "api_confirm_flow"

    gated = _submit(client, PLAN_TEXT, session_id)
    assert gated["needs_confirmation"] is True
    assert gated["confirmation_message"]

    confirmed = client.post(f"/api/v1/tasks/sessions/{session_id}/confirm")
    assert confirmed.status_code == 200
    outcome = _wait_result(client, confirmed.json()["task_id"])
    assert outcome["success"] is True, outcome["message"]
    assert outcome["data"]["slots"] == 3

    # 规划结果落在会话状态里，后续指令读得到
    progress = _submit(client, "查看进度", session_id)
    assert progress["data"]["phase"] == "planned"


def test_cancelled_confirmation_leaves_state_untouched(client):
    session_id = "api_cancel_flow"

    assert _submit(client, PLAN_TEXT, session_id)["needs_confirmation"] is True

    cancelled = client.post(f"/api/v1/tasks/sessions/{session_id}/cancel")
    assert cancelled.status_code == 200
    outcome = _wait_result(client, cancelled.json()["task_id"])
    assert outcome["success"] is True

    assert _submit(client, "查看进度", session_id)["data"]["slots"] == 0


def test_confirm_without_pending_operation(client):
    """重复确认：第二次必须如实失败，而不是把「跑完了」当成「成功了」。"""
    session_id = "api_confirm_twice"
    assert _submit(client, PLAN_TEXT, session_id)["needs_confirmation"] is True

    first = client.post(f"/api/v1/tasks/sessions/{session_id}/confirm")
    assert _wait_result(client, first.json()["task_id"])["success"] is True

    second = client.post(f"/api/v1/tasks/sessions/{session_id}/confirm")
    outcome = _wait_result(client, second.json()["task_id"])
    assert outcome["success"] is False
    assert "没有待确认" in (outcome["message"] or "")
