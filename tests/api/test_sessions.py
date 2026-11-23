"""会话接口测试：真实生命周期，会话是任务与确认门的工作对象。"""

SESSION_ID = "api_sess_lifecycle"


def test_session_lifecycle(client):
    created = client.post("/api/v1/sessions", json={"session_id": SESSION_ID})
    assert created.status_code == 200
    body = created.json()
    assert body["session_id"] == SESSION_ID
    assert body["phase"] == "idle"

    assert client.post("/api/v1/sessions", json={"session_id": SESSION_ID}).status_code == 409

    assert client.delete(f"/api/v1/sessions/{SESSION_ID}").status_code == 200
    assert client.get(f"/api/v1/sessions/{SESSION_ID}").status_code == 404


def test_session_detail_reports_empty_counts(client):
    session_id = client.post("/api/v1/sessions", json={}).json()["session_id"]

    detail = client.get(f"/api/v1/sessions/{session_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["session_id"] == session_id
    assert body["phase"] == "idle"
    assert (body["assets"], body["slots"], body["matched_slots"]) == (0, 0, 0)


def test_unknown_session_404(client):
    assert client.get("/api/v1/sessions/does-not-exist").status_code == 404
    assert client.delete("/api/v1/sessions/does-not-exist").status_code == 404
