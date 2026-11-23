"""管理员后台、API Key 与数据范围测试"""
from __future__ import annotations

import os
import sqlite3

from app.core.security import hash_password
from app.models.base import utcnow

PREFIX = "/api/v1"


def _db_path() -> str:
    return os.environ["DATABASE_URL"].split("sqlite+aiosqlite:///", 1)[1]


def _insert_user(
    name: str,
    role: str,
    *,
    department: str | None = None,
    email: str | None = None,
    password: str = "Passw0rd!",
) -> None:
    now = str(utcnow())
    conn = sqlite3.connect(_db_path())
    try:
        conn.execute(
            '''
            INSERT INTO "user"
                (company_id, name, email, password, role, department, status, email_verified_at,
                 login_fail_count, token_version, create_time, update_time)
            VALUES (1, ?, ?, ?, ?, ?, 'active', ?, 0, 0, ?, ?)
            ''',
            (name, email or f"{name}@example.com", hash_password(password), role,
             department, now, now, now),
        )
        conn.commit()
    finally:
        conn.close()


def _login(client, name: str, password: str = "Passw0rd!") -> dict[str, str]:
    resp = client.post(f"{PREFIX}/auth/login", json={"account": name, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _admin_headers(client, suffix: str) -> dict[str, str]:
    name = f"adm_{suffix}"
    _insert_user(name, "admin")
    return _login(client, name)


def _create_job(client, headers: dict[str, str], title: str, department: str) -> dict:
    skill = client.post(
        f"{PREFIX}/skills", headers=headers, json={"name": f"skill_{title}"}
    )
    assert skill.status_code in (200, 201), skill.text
    resp = client.post(
        f"{PREFIX}/jobs",
        headers=headers,
        json={
            "title": title,
            "department": department,
            "description": "d",
            "requirements": "r",
            "skills": [skill.json()["id"]],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_candidate(client, headers: dict[str, str], name: str, phone: str) -> dict:
    resp = client.post(
        f"{PREFIX}/candidates",
        headers=headers,
        json={"name": name, "phone": phone, "email": f"{phone}@example.com"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _apply(client, headers: dict[str, str], job_id: int, candidate_id: int) -> dict:
    resp = client.post(
        f"{PREFIX}/applications",
        headers=headers,
        json={"job_id": job_id, "candidate_id": candidate_id},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------- 管理员用户管理
def test_admin_user_role_disable_delete(client):
    admin = _admin_headers(client, "user")
    _insert_user("adm_target", "recruiter")
    users = client.get(f"{PREFIX}/admin/users", headers=admin)
    assert users.status_code == 200, users.text
    target = next(item for item in users.json() if item["name"] == "adm_target")

    updated = client.patch(
        f"{PREFIX}/admin/users/{target['id']}",
        headers=admin,
        json={"role": "manager", "department": "技术部"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["role"] == "manager"
    assert updated.json()["department"] == "技术部"

    disabled = client.patch(
        f"{PREFIX}/admin/users/{target['id']}", headers=admin, json={"status": "disabled"}
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["status"] == "disabled"
    assert client.post(
        f"{PREFIX}/auth/login",
        json={"account": "adm_target", "password": "Passw0rd!"},
    ).status_code != 200

    deleted = client.delete(f"{PREFIX}/admin/users/{target['id']}", headers=admin)
    assert deleted.status_code == 204, deleted.text
    names = {item["name"] for item in client.get(f"{PREFIX}/admin/users", headers=admin).json()}
    assert "adm_target" not in names
    with_deleted = client.get(
        f"{PREFIX}/admin/users?include_deleted=true", headers=admin
    ).json()
    row = next(item for item in with_deleted if item["id"] == target["id"])
    assert row["status"] == "deleted"


def test_admin_cannot_disable_self(client):
    admin = _admin_headers(client, "self")
    me = client.get(f"{PREFIX}/auth/me", headers=admin).json()
    resp = client.patch(
        f"{PREFIX}/admin/users/{me['id']}", headers=admin, json={"status": "disabled"}
    )
    assert resp.status_code == 400
    assert "自己" in resp.json()["error"]["message"]


# ---------------------------------------------------------------- 系统配置 / 审计
def test_admin_system_config_and_audit(client):
    admin = _admin_headers(client, "config")
    configs = client.get(f"{PREFIX}/admin/system-config", headers=admin)
    assert configs.status_code == 200, configs.text
    keys = {item["key"] for item in configs.json()}
    assert "resume.max_upload_mb" in keys

    bad = client.put(
        f"{PREFIX}/admin/system-config/resume.max_upload_mb",
        headers=admin,
        json={"value": 0},
    )
    assert bad.status_code == 400

    ok = client.put(
        f"{PREFIX}/admin/system-config/resume.max_upload_mb",
        headers=admin,
        json={"value": 30, "description": "测试调整"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["value"] == 30

    logs = client.get(
        f"{PREFIX}/admin/audit-logs?action=admin.config.update", headers=admin
    )
    assert logs.status_code == 200, logs.text
    assert logs.json()["total"] >= 1
    assert logs.json()["items"][0]["user_name"].startswith("adm_config")


# ---------------------------------------------------------------- API Key
def test_api_key_lifecycle_and_auth(client):
    _insert_user("key_user", "recruiter")
    headers = _login(client, "key_user")

    created = client.post(
        f"{PREFIX}/api-keys", headers=headers, json={"name": "脚本调用"}
    )
    assert created.status_code == 201, created.text
    raw = created.json()["key"]
    key_id = created.json()["id"]
    assert raw.startswith("tm_")
    assert created.json()["status"] == "active"

    # 明文只在创建时返回；列表里只显示前缀
    listed = client.get(f"{PREFIX}/api-keys", headers=headers).json()["items"]
    assert listed[0]["prefix"] == raw[:11]
    assert "key" not in listed[0]

    me = client.get(f"{PREFIX}/auth/me", headers={"X-API-Key": raw})
    assert me.status_code == 200, me.text
    assert me.json()["name"] == "key_user"

    # 管理员能看到全部 Key
    admin = _admin_headers(client, "keys")
    all_keys = client.get(f"{PREFIX}/admin/api-keys", headers=admin)
    assert all_keys.status_code == 200
    assert any(item["id"] == key_id and item["user_name"] == "key_user" for item in all_keys.json()["items"])

    # 吊销后立即失效
    assert client.delete(f"{PREFIX}/api-keys/{key_id}", headers=headers).status_code == 204
    assert client.get(f"{PREFIX}/auth/me", headers={"X-API-Key": raw}).status_code == 401


def test_api_key_expired_and_cross_user_revoke(client):
    _insert_user("key_owner", "recruiter")
    owner = _login(client, "key_owner")
    _insert_user("key_other", "recruiter")
    other = _login(client, "key_other")

    created = client.post(f"{PREFIX}/api-keys", headers=owner, json={"name": "过期测试"}).json()
    conn = sqlite3.connect(_db_path())
    try:
        conn.execute("UPDATE api_key SET expires_at = ? WHERE id = ?", ("2000-01-01 00:00:00", created["id"]))
        conn.commit()
    finally:
        conn.close()
    assert client.get(f"{PREFIX}/auth/me", headers={"X-API-Key": created["key"]}).status_code == 401
    assert client.delete(f"{PREFIX}/api-keys/{created['id']}", headers=other).status_code == 404


def test_api_key_can_be_disabled_by_system_config(client):
    _insert_user("key_switch", "recruiter")
    headers = _login(client, "key_switch")
    created = client.post(f"{PREFIX}/api-keys", headers=headers, json={"name": "开关测试"}).json()
    admin = _admin_headers(client, "switch")

    try:
        assert client.put(
            f"{PREFIX}/admin/system-config/security.api_key_enabled",
            headers=admin,
            json={"value": False},
        ).status_code == 200
        assert client.get(f"{PREFIX}/auth/me", headers={"X-API-Key": created["key"]}).status_code == 401
    finally:
        client.put(
            f"{PREFIX}/admin/system-config/security.api_key_enabled",
            headers=admin,
            json={"value": True},
        )
    assert client.get(f"{PREFIX}/auth/me", headers={"X-API-Key": created["key"]}).status_code == 200


# ---------------------------------------------------------------- 数据范围
def test_manager_department_data_scope(client):
    _insert_user("scope_rec_a", "recruiter")
    _insert_user("scope_rec_b", "recruiter")
    _insert_user("scope_mgr_dept", "manager", department="技术部")
    _insert_user("scope_mgr_all", "manager")
    rec_a = _login(client, "scope_rec_a")
    rec_b = _login(client, "scope_rec_b")
    mgr_dept = _login(client, "scope_mgr_dept")
    mgr_all = _login(client, "scope_mgr_all")
    admin = _admin_headers(client, "scope")

    job_a = _create_job(client, rec_a, "后端工程师", "技术部")
    job_b = _create_job(client, rec_b, "市场经理", "市场部")
    cand_a = _create_candidate(client, rec_a, "候选人甲", "13700000001")
    cand_b = _create_candidate(client, rec_b, "候选人乙", "13700000002")
    _apply(client, rec_a, job_a["id"], cand_a["id"])
    _apply(client, rec_b, job_b["id"], cand_b["id"])

    # 部门 manager 只看到本部门职位/候选人
    dept_jobs = {item["id"] for item in client.get(f"{PREFIX}/jobs", headers=mgr_dept).json()["items"]}
    assert job_a["id"] in dept_jobs
    assert job_b["id"] not in dept_jobs
    assert client.get(f"{PREFIX}/jobs/{job_b['id']}", headers=mgr_dept).status_code == 403
    assert client.get(f"{PREFIX}/jobs/{job_a['id']}", headers=mgr_dept).status_code == 200

    dept_candidates = {
        item["id"] for item in client.get(f"{PREFIX}/candidates", headers=mgr_dept).json()["items"]
    }
    assert cand_a["id"] in dept_candidates
    assert cand_b["id"] not in dept_candidates
    assert client.get(f"{PREFIX}/candidates/{cand_b['id']}", headers=mgr_dept).status_code == 403
    assert client.get(f"{PREFIX}/candidates/{cand_a['id']}", headers=mgr_dept).status_code == 200

    # 未分配部门的 manager 视为全公司
    all_jobs = {item["id"] for item in client.get(f"{PREFIX}/jobs", headers=mgr_all).json()["items"]}
    assert {job_a["id"], job_b["id"]} <= all_jobs

    # recruiter 只看自己的职位/候选人；他人的草稿不可见
    rec_jobs = {item["id"] for item in client.get(f"{PREFIX}/jobs", headers=rec_a).json()["items"]}
    assert job_a["id"] in rec_jobs
    assert job_b["id"] not in rec_jobs
    assert client.get(f"{PREFIX}/candidates/{cand_b['id']}", headers=rec_a).status_code == 403

    # admin 全公司可见
    admin_candidates = {
        item["id"] for item in client.get(f"{PREFIX}/candidates", headers=admin).json()["items"]
    }
    assert {cand_a["id"], cand_b["id"]} <= admin_candidates


def test_manager_cannot_approve_other_department_job(client):
    _insert_user("scope_rec_c", "recruiter")
    _insert_user("scope_mgr_market", "manager", department="市场部")
    rec = _login(client, "scope_rec_c")
    mgr = _login(client, "scope_mgr_market")

    job = _create_job(client, rec, "技术岗位", "技术部")
    assert client.post(f"{PREFIX}/jobs/{job['id']}/submit", headers=rec).status_code == 200

    resp = client.post(f"{PREFIX}/jobs/{job['id']}/approve", headers=mgr)
    assert resp.status_code == 403
    assert "无权审批" in resp.json()["error"]["message"]
