"""角色权限与登出失效测试"""
from __future__ import annotations

import os
import sqlite3

from app.core.security import hash_password
from app.models.base import utcnow

PREFIX = "/api/v1/auth"
ADMIN_URL = "/api/v1/admin/users"


def _db_path() -> str:
    return os.environ["DATABASE_URL"].split("sqlite+aiosqlite:///", 1)[1]


def _insert_user(name: str, email: str, role: str, password: str = "Passw0rd!") -> None:
    now = str(utcnow())
    conn = sqlite3.connect(_db_path())
    try:
        conn.execute(
            '''
            INSERT INTO "user"
                (company_id, name, email, password, role, status, email_verified_at,
                 login_fail_count, token_version, create_time, update_time)
            VALUES (1, ?, ?, ?, ?, 'active', ?, 0, 0, ?, ?)
            ''',
            (name, email, hash_password(password), role, now, now, now),
        )
        conn.commit()
    finally:
        conn.close()


def _set_role(name: str, role: str) -> None:
    conn = sqlite3.connect(_db_path())
    try:
        conn.execute('UPDATE "user" SET role = ? WHERE name = ?', (role, name))
        conn.commit()
    finally:
        conn.close()


def _register_and_login(client, email_capture, name: str, email: str) -> dict:
    resp = client.post(
        PREFIX + "/register",
        json={
            "name": name,
            "email": email,
            "password": "Passw0rd!",
            "mode": "join",
            "invite_code": "TESTJOIN",
        },
    )
    assert resp.status_code == 201, resp.text
    token = email_capture["verify"][-1].split("token=", 1)[1]
    assert client.post(PREFIX + "/verify-email", json={"token": token}).status_code == 200

    login = client.post(PREFIX + "/login", json={"account": name, "password": "Passw0rd!"})
    assert login.status_code == 200, login.text
    return login.json()


def test_recruiter_cannot_access_admin_api(client, email_capture):
    tokens = _register_and_login(client, email_capture, "rbac_recruiter", "rbac_recruiter@example.com")
    resp = client.get(
        ADMIN_URL, headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert resp.status_code == 403
    assert "无权访问" in resp.json()["error"]["message"]


def test_admin_can_access_admin_api(client, email_capture):
    _insert_user("rbac_admin", "rbac_admin@example.com", "admin")
    login = client.post(
        PREFIX + "/login", json={"account": "rbac_admin", "password": "Passw0rd!"}
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]

    resp = client.get(ADMIN_URL, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    names = {user["name"] for user in resp.json()}
    assert "rbac_admin" in names


def test_role_change_takes_effect_immediately(client, email_capture):
    _insert_user("rbac_demote", "rbac_demote@example.com", "admin")
    login = client.post(
        PREFIX + "/login", json={"account": "rbac_demote", "password": "Passw0rd!"}
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get(ADMIN_URL, headers=headers).status_code == 200

    # 直接改库降级，旧 token 里的 role 仍是 admin，但鉴权以数据库为准
    _set_role("rbac_demote", "recruiter")
    assert client.get(ADMIN_URL, headers=headers).status_code == 403


def test_logout_invalidates_old_tokens(client, email_capture):
    tokens = _register_and_login(client, email_capture, "rbac_logout", "rbac_logout@example.com")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    assert client.post(PREFIX + "/logout", headers=headers).status_code == 200

    # 旧 access token 立即失效
    assert client.get(PREFIX + "/me", headers=headers).status_code == 401
    # 旧 refresh token 也失效
    resp = client.post(PREFIX + "/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 401
