"""账号注销：仅招聘专员/用人经理可用，注销后清理其创建的数据"""
from __future__ import annotations

import uuid

PREFIX = "/api/v1"


def _register(client, email_capture, name: str, *, role: str = "recruiter") -> dict:
    resp = client.post(
        f"{PREFIX}/auth/register",
        json={
            "name": name,
            "email": f"{name}@example.com",
            "password": "Passw0rd!",
            "mode": "join",
            "invite_code": "TESTJOIN",
            "role": role,
        },
    )
    assert resp.status_code == 201, resp.text
    token = email_capture["verify"][-1].split("token=", 1)[1]
    client.post(f"{PREFIX}/auth/verify-email", json={"token": token})
    login = client.post(
        f"{PREFIX}/auth/login", json={"account": name, "password": "Passw0rd!"}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_job(client, headers, title: str) -> int:
    skill = client.post(
        f"{PREFIX}/skills",
        headers=headers,
        json={"name": f"skill_{uuid.uuid4().hex[:6]}", "aliases": [], "category": "language"},
    )
    assert skill.status_code in (200, 201), skill.text
    job = client.post(
        f"{PREFIX}/jobs",
        headers=headers,
        json={
            "title": title,
            "department": "研发部",
            "location": "上海",
            "description": "职位描述",
            "requirements": "职位要求",
            "skills": [skill.json()["id"]],
        },
    )
    assert job.status_code == 201, job.text
    return job.json()["id"]


def test_cancel_account_cleans_own_data(client, email_capture):
    suffix = uuid.uuid4().hex[:6]
    recruiter = _register(client, email_capture, f"cancel_user_{suffix}")
    manager = _register(client, email_capture, f"cancel_manager_{suffix}", role="manager")
    job_id = _create_job(client, recruiter, f"待清理职位{suffix}")
    assert client.get(f"{PREFIX}/jobs/{job_id}", headers=manager).status_code == 200

    wrong = client.request(
        "DELETE",
        f"{PREFIX}/auth/me",
        headers=recruiter,
        json={"password": "WrongPass1!"},
    )
    assert wrong.status_code == 400

    resp = client.request(
        "DELETE", f"{PREFIX}/auth/me", headers=recruiter, json={"password": "Passw0rd!"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted_jobs"] == 1

    # 注销后令牌立即失效
    assert client.get(f"{PREFIX}/auth/me", headers=recruiter).status_code == 401
    assert (
        client.post(
            f"{PREFIX}/auth/login",
            json={"account": f"cancel_user_{suffix}", "password": "Passw0rd!"},
        ).status_code
        != 200
    )

    # 职位确实被清理
    assert client.get(f"{PREFIX}/jobs/{job_id}", headers=manager).status_code == 404


def test_admin_cannot_cancel_account(client, email_capture):
    suffix = uuid.uuid4().hex[:6]
    name = f"cancel_admin_{suffix}"
    resp = client.post(
        f"{PREFIX}/auth/register",
        json={
            "name": name,
            "email": f"{name}@example.com",
            "password": "Passw0rd!",
            "mode": "create",
            "company_name": f"注销测试公司{suffix}",
        },
    )
    assert resp.status_code == 201, resp.text
    token = email_capture["verify"][-1].split("token=", 1)[1]
    client.post(f"{PREFIX}/auth/verify-email", json={"token": token})
    login = client.post(
        f"{PREFIX}/auth/login", json={"account": name, "password": "Passw0rd!"}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    denied = client.request(
        "DELETE", f"{PREFIX}/auth/me", headers=headers, json={"password": "Passw0rd!"}
    )
    assert denied.status_code == 403
