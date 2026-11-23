"""多租户隔离测试：建司 / 邀请码加入 / 跨公司不可见 / 平台超管"""
from __future__ import annotations

import os
import sqlite3
import uuid

from app.core.security import hash_password
from app.models.base import utcnow

PREFIX = "/api/v1"


def _db_path() -> str:
    return os.environ["DATABASE_URL"].split("sqlite+aiosqlite:///", 1)[1]


def _register(client, email_capture, name: str, *, mode: str, **extra) -> dict:
    payload = {
        "name": name,
        "email": f"{name}@example.com",
        "password": "Passw0rd!",
        "mode": mode,
        **extra,
    }
    resp = client.post(f"{PREFIX}/auth/register", json=payload)
    assert resp.status_code == 201, resp.text

    link = email_capture["verify"][-1]
    token = link.split("token=", 1)[1]
    assert client.post(f"{PREFIX}/auth/verify-email", json={"token": token}).status_code == 200

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


def _insert_superadmin(name: str) -> None:
    now = str(utcnow())
    conn = sqlite3.connect(_db_path())
    try:
        conn.execute(
            '''
            INSERT INTO "user"
                (company_id, name, email, password, role, status, email_verified_at,
                 login_fail_count, token_version, create_time, update_time)
            VALUES (NULL, ?, ?, ?, 'superadmin', 'active', ?, 0, 0, ?, ?)
            ''',
            (name, f"{name}@example.com", hash_password("Passw0rd!"), now, now, now),
        )
        conn.commit()
    finally:
        conn.close()


def _login(client, name: str) -> dict[str, str]:
    resp = client.post(
        f"{PREFIX}/auth/login", json={"account": name, "password": "Passw0rd!"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_company_data_is_isolated(client, email_capture):
    suffix = uuid.uuid4().hex[:6]
    admin_a = _register(
        client, email_capture, f"tenant_a_{suffix}", mode="create", company_name=f"A公司{suffix}"
    )
    admin_b = _register(
        client, email_capture, f"tenant_b_{suffix}", mode="create", company_name=f"B公司{suffix}"
    )

    job_a = _create_job(client, admin_a, f"A职位{suffix}")

    list_a = client.get(f"{PREFIX}/jobs", headers=admin_a)
    list_b = client.get(f"{PREFIX}/jobs", headers=admin_b)
    assert any(item["id"] == job_a for item in list_a.json()["items"])
    assert all(item["id"] != job_a for item in list_b.json()["items"])

    # 跨公司详情按 404 处理，不暴露存在性
    assert client.get(f"{PREFIX}/jobs/{job_a}", headers=admin_b).status_code == 404

    company_a = client.get(f"{PREFIX}/company/current", headers=admin_a).json()
    company_b = client.get(f"{PREFIX}/company/current", headers=admin_b).json()
    assert company_a["id"] != company_b["id"]
    assert company_a["invite_code"] and company_b["invite_code"]


def test_invite_join_same_company(client, email_capture):
    suffix = uuid.uuid4().hex[:6]
    admin = _register(
        client, email_capture, f"join_admin_{suffix}", mode="create", company_name=f"加入公司{suffix}"
    )
    job_id = _create_job(client, admin, f"加入职位{suffix}")
    assert client.post(f"{PREFIX}/jobs/{job_id}/publish", headers=admin).status_code == 200
    company = client.get(f"{PREFIX}/company/current", headers=admin).json()

    member = _register(
        client,
        email_capture,
        f"join_member_{suffix}",
        mode="join",
        invite_code=company["invite_code"],
        role="recruiter",
    )
    member_company = client.get(f"{PREFIX}/company/current", headers=member).json()
    assert member_company["id"] == company["id"]
    assert any(
        item["id"] == job_id
        for item in client.get(f"{PREFIX}/jobs", headers=member).json()["items"]
    )


def test_invalid_invite_rejected(client):
    resp = client.post(
        f"{PREFIX}/auth/register",
        json={
            "name": "bad_invite_user",
            "email": "bad_invite_user@example.com",
            "password": "Passw0rd!",
            "mode": "join",
            "invite_code": "NOPE9999",
        },
    )
    assert resp.status_code == 400


def test_superadmin_platform_and_company_disable(client, email_capture):
    suffix = uuid.uuid4().hex[:6]
    admin = _register(
        client, email_capture, f"plat_admin_{suffix}", mode="create", company_name=f"平台公司{suffix}"
    )
    company = client.get(f"{PREFIX}/company/current", headers=admin).json()

    # 普通公司管理员不能进平台后台
    assert client.get(f"{PREFIX}/platform/companies", headers=admin).status_code == 403

    super_name = f"super_{suffix}"
    _insert_superadmin(super_name)
    superadmin = _login(client, super_name)

    companies = client.get(f"{PREFIX}/platform/companies", headers=superadmin)
    assert companies.status_code == 200, companies.text
    assert any(item["id"] == company["id"] for item in companies.json())

    # 停用后，该公司成员的请求被拒绝
    disabled = client.patch(
        f"{PREFIX}/platform/companies/{company['id']}",
        headers=superadmin,
        json={"status": "disabled"},
    )
    assert disabled.status_code == 200, disabled.text
    blocked = client.get(f"{PREFIX}/company/current", headers=admin)
    assert blocked.status_code == 403
    assert "停用" in blocked.json()["error"]["message"]
