"""认证流程测试：注册 / 邮箱验证 / 登录 / 刷新 / 找回密码"""
from __future__ import annotations

PREFIX = "/api/v1/auth"


def _register(client, name: str, email: str, password: str = "Passw0rd!"):
    return client.post(
        PREFIX + "/register",
        json={"name": name, "email": email, "password": password},
    )


def _token_from(link: str) -> str:
    return link.split("token=", 1)[1]


def _verify(client, emails: dict[str, list[str]], kind: str = "verify"):
    token = _token_from(emails[kind][-1])
    return client.post(PREFIX + "/verify-email", json={"token": token})


def _register_verified(client, emails, name: str, email: str, password: str = "Passw0rd!"):
    assert _register(client, name, email, password).status_code == 201
    assert _verify(client, emails).status_code == 200


def test_register_requires_email_verification(client, email_capture):
    resp = _register(client, "user_one", "user_one@example.com")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["user"]["role"] == "recruiter"
    assert body["user"]["email_verified"] is False
    assert body["email_sent"] is True
    assert len(email_capture["verify"]) == 1

    # 未验证不能登录
    blocked = client.post(
        PREFIX + "/login", json={"account": "user_one", "password": "Passw0rd!"}
    )
    assert blocked.status_code == 403
    assert "邮箱未验证" in blocked.json()["error"]["message"]

    # 用邮件里的链接验证后即可登录
    assert _verify(client, email_capture).status_code == 200
    login = client.post(
        PREFIX + "/login", json={"account": "user_one", "password": "Passw0rd!"}
    )
    assert login.status_code == 200, login.text
    tokens = login.json()
    assert tokens["access_token"] and tokens["refresh_token"]

    me = client.get(PREFIX + "/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email_verified"] is True


def test_register_duplicate(client):
    assert _register(client, "dup_user", "dup@example.com").status_code == 201
    assert _register(client, "dup_user", "dup@example.com").status_code == 409


def test_register_weak_password(client):
    resp = client.post(
        PREFIX + "/register",
        json={"name": "weak_user", "email": "weak@example.com", "password": "abcdefgh"},
    )
    assert resp.status_code == 422


def test_login_wrong_password(client, email_capture):
    _register_verified(client, email_capture, "fail_user", "fail@example.com")
    resp = client.post(
        PREFIX + "/login", json={"account": "fail_user", "password": "WrongPass1"}
    )
    assert resp.status_code == 401
    assert resp.json()["success"] is False


def test_refresh_token(client, email_capture):
    _register_verified(client, email_capture, "refresh_user", "refresh@example.com")
    login = client.post(
        PREFIX + "/login", json={"account": "refresh_user", "password": "Passw0rd!"}
    ).json()

    resp = client.post(PREFIX + "/refresh", json={"refresh_token": login["refresh_token"]})
    assert resp.status_code == 200
    assert resp.json()["access_token"]

    bad = client.post(PREFIX + "/refresh", json={"refresh_token": "not-a-token"})
    assert bad.status_code == 401


def test_forgot_password_unknown_email_is_generic(client):
    resp = client.post(PREFIX + "/forgot-password", json={"email": "nobody@example.com"})
    assert resp.status_code == 200
    assert "如果该邮箱已注册" in resp.json()["message"]


def test_reset_password_flow(client, email_capture):
    _register(client, "reset_user", "reset@example.com")

    assert (
        client.post(PREFIX + "/forgot-password", json={"email": "reset@example.com"}).status_code
        == 200
    )
    assert len(email_capture["reset"]) == 1
    token = _token_from(email_capture["reset"][-1])

    reset = client.post(
        PREFIX + "/reset-password", json={"token": token, "new_password": "NewPass123"}
    )
    assert reset.status_code == 200, reset.text

    # 重置后邮箱视为已验证，可用新密码登录
    login = client.post(
        PREFIX + "/login", json={"account": "reset@example.com", "password": "NewPass123"}
    )
    assert login.status_code == 200, login.text

    # token 一次性
    again = client.post(
        PREFIX + "/reset-password", json={"token": token, "new_password": "Another123"}
    )
    assert again.status_code == 400


def test_verify_token_single_use(client, email_capture):
    _register(client, "verify_user", "verify@example.com")
    assert _verify(client, email_capture).status_code == 200
    assert _verify(client, email_capture).status_code == 400


def test_resend_verification(client, email_capture):
    _register(client, "resend_user", "resend@example.com")
    assert len(email_capture["verify"]) == 1

    resp = client.post(PREFIX + "/resend-verification", json={"email": "resend@example.com"})
    assert resp.status_code == 200
    assert len(email_capture["verify"]) == 2

    # 新链接可用，旧链接已作废
    old_token = _token_from(email_capture["verify"][0])
    new_token = _token_from(email_capture["verify"][1])
    assert client.post(PREFIX + "/verify-email", json={"token": old_token}).status_code == 400
    assert client.post(PREFIX + "/verify-email", json={"token": new_token}).status_code == 200


def test_dev_mode_prints_link_to_console(client, monkeypatch):
    """EMAIL_HOST 为空：不发信，注册后仍未验证，提示查看控制台"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "EMAIL_HOST", "")

    resp = _register(client, "dev_user", "dev@example.com")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email_sent"] is False
    assert body["user"]["email_verified"] is False
    assert "控制台" in body["message"]

    blocked = client.post(
        PREFIX + "/login", json={"account": "dev_user", "password": "Passw0rd!"}
    )
    assert blocked.status_code == 403
