"""阶段一冒烟测试：健康检查与根路径"""


def test_root(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["app"] == "TalentMatch"
    assert body["docs"] == "/docs"


def test_healthz(client):
    resp = client.get("/api/v1/healthz")
    assert resp.status_code == 200

    body = resp.json()
    assert body["status"] in ("ok", "degraded")
    assert body["components"]["database"]["ok"] is True
    assert body["components"]["storage"]["ok"] is True
    assert "version" in body


def test_docs_available(client):
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    assert "/api/v1/healthz" in schema["paths"]
