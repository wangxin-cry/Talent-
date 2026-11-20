"""职位管理测试：CRUD、状态机、发布校验、技能归一、JD 生成"""
from __future__ import annotations

PREFIX = "/api/v1"


def _auth_headers(client, email_capture, suffix: str) -> dict[str, str]:
    name = f"job_{suffix}"
    email = f"job_{suffix}@example.com"
    resp = client.post(
        f"{PREFIX}/auth/register",
        json={"name": name, "email": email, "password": "Passw0rd!"},
    )
    assert resp.status_code == 201, resp.text
    token = email_capture["verify"][-1].split("token=", 1)[1]
    assert client.post(f"{PREFIX}/auth/verify-email", json={"token": token}).status_code == 200

    login = client.post(f"{PREFIX}/auth/login", json={"account": name, "password": "Passw0rd!"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_skill(client, headers, name: str, aliases: list[str] | None = None) -> int:
    resp = client.post(
        f"{PREFIX}/skills",
        json={"name": name, "aliases": aliases or [], "category": "middleware"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_job_crud_and_state_machine(client, email_capture):
    headers = _auth_headers(client, email_capture, "flow")
    skill_id = _create_skill(client, headers, "Kubernetes", ["K8s"])

    created = client.post(
        f"{PREFIX}/jobs",
        json={"title": "高级后端工程师", "department": "研发部", "skills": [skill_id]},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    job = created.json()
    assert job["status"] == "draft"
    assert job["jd_version"] == 1
    assert [s["name"] for s in job["skills"]] == ["Kubernetes"]
    job_id = job["id"]

    # 缺描述 / 要求 → 发布被拒
    failed = client.post(f"{PREFIX}/jobs/{job_id}/publish", headers=headers)
    assert failed.status_code == 400
    assert "职位描述" in failed.json()["error"]["message"]

    updated = client.put(
        f"{PREFIX}/jobs/{job_id}",
        json={"description": "负责后端服务开发", "requirements": "熟悉 Python 与 K8s"},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["jd_version"] == 2

    published = client.post(f"{PREFIX}/jobs/{job_id}/publish", headers=headers)
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    assert published.json()["published_at"] is not None

    # 非法流转：published 不能回到 published / draft
    again = client.post(f"{PREFIX}/jobs/{job_id}/publish", headers=headers)
    assert again.status_code == 400
    assert "状态非法" in again.json()["error"]["message"]

    closed = client.post(f"{PREFIX}/jobs/{job_id}/close", headers=headers)
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"

    archived = client.post(f"{PREFIX}/jobs/{job_id}/archive", headers=headers)
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"

    # 终态不可再流转
    assert client.post(f"{PREFIX}/jobs/{job_id}/close", headers=headers).status_code == 400


def test_job_list_filter_and_detail(client, email_capture):
    headers = _auth_headers(client, email_capture, "list")
    skill_id = _create_skill(client, headers, "Redis", ["Cache"])

    created = client.post(
        f"{PREFIX}/jobs",
        json={
            "title": "缓存平台工程师",
            "skills": [skill_id],
            "description": "负责缓存平台建设",
            "requirements": "熟悉 Redis",
        },
        headers=headers,
    )
    assert created.status_code == 201
    job_id = created.json()["id"]
    assert client.post(f"{PREFIX}/jobs/{job_id}/publish", headers=headers).status_code == 200

    listed = client.get(
        f"{PREFIX}/jobs", params={"status": "published", "q": "缓存"}, headers=headers
    )
    assert listed.status_code == 200, listed.text
    payload = listed.json()
    assert payload["total"] >= 1
    assert any(item["id"] == job_id for item in payload["items"])

    detail = client.get(f"{PREFIX}/jobs/{job_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["title"] == "缓存平台工程师"


def test_generate_jd_normalizes_skills(client, email_capture):
    headers = _auth_headers(client, email_capture, "jd")
    _create_skill(client, headers, "Kubernetes", ["K8s"])

    resp = client.post(
        f"{PREFIX}/jobs/generate-jd",
        json={"title": "后端工程师", "department": "平台研发部", "keywords": ["K8s", "Python"]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    names = [skill["name"] for skill in payload["skills"]]
    assert "Kubernetes" in names  # K8s 归一
    assert "Python" in names
    assert "后端工程师" in payload["description"]
    assert payload["requirements"]
    assert len(payload["must_have_skills"]) <= 2
    assert payload["ai_generated"] is False
    assert payload["note"]

    # 词表没有的关键词自动建技能，不丢信息
    resp2 = client.post(
        f"{PREFIX}/jobs/generate-jd",
        json={"title": "算法工程师", "keywords": ["内部特征平台X"]},
        headers=headers,
    )
    assert resp2.status_code == 200
    assert "内部特征平台X" in [skill["name"] for skill in resp2.json()["skills"]]
