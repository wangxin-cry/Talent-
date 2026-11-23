"""认证流程测试：注册 / 邮箱验证 / 登录 / 刷新 / 找回密码 / 个人资料 / 头像"""
from __future__ import annotations

import io

import pytest
from PIL import Image

PREFIX = "/api/v1/auth"


def _register(client, name: str, email: str, password: str = "Passw0rd!"):
    return client.post(
        PREFIX + "/register",
        json={
            "name": name,
            "email": email,
            "password": password,
            "mode": "join",
            "invite_code": "TESTJOIN",
        },
    )


def _token_from(link: str) -> str:
    return link.split("token=", 1)[1]


def _verify(client, emails: dict[str, list[str]], kind: str = "verify"):
    token = _token_from(emails[kind][-1])
    return client.post(PREFIX + "/verify-email", json={"token": token})


def _register_verified(client, emails, name: str, email: str, password: str = "Passw0rd!"):
    assert _register(client, name, email, password).status_code == 201
    assert _verify(client, emails).status_code == 200


def test_register_as_manager(client):
    resp = client.post(
        PREFIX + "/register",
        json={
            "name": "manager_one",
            "email": "manager_one@example.com",
            "password": "Passw0rd!",
            "role": "manager",
            "mode": "join",
            "invite_code": "TESTJOIN",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["user"]["role"] == "manager"


def test_register_rejects_admin_role(client):
    resp = client.post(
        PREFIX + "/register",
        json={
            "name": "fake_admin",
            "email": "fake_admin@example.com",
            "password": "Passw0rd!",
            "role": "admin",
        },
    )
    assert resp.status_code == 422


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


def test_update_profile(client, email_capture):
    _register_verified(client, email_capture, "profile_user", "profile_user@example.com")
    login = client.post(
        PREFIX + "/login", json={"account": "profile_user", "password": "Passw0rd!"}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    updated = client.patch(
        PREFIX + "/me",
        headers=headers,
        json={"nickname": "小雨", "phone": "13800000000", "bio": "专注后端招聘"},
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["nickname"] == "小雨"
    assert body["phone"] == "13800000000"
    assert body["bio"] == "专注后端招聘"
    assert body["avatar_url"] is None
    # 登录名、邮箱、角色不能被个人资料接口修改
    assert body["name"] == "profile_user"
    assert body["email"] == "profile_user@example.com"
    assert body["role"] == "recruiter"

    cleared = client.patch(
        PREFIX + "/me",
        headers=headers,
        json={"nickname": "", "phone": "", "bio": ""},
    )
    assert cleared.status_code == 200
    assert cleared.json()["nickname"] is None
    assert cleared.json()["phone"] is None
    assert cleared.json()["bio"] is None

    # 头像不再接受外部 URL，只能走上传接口；多余字段被忽略
    ignored = client.patch(
        PREFIX + "/me", headers=headers, json={"avatar_url": "javascript:alert(1)"}
    )
    assert ignored.status_code == 200
    assert ignored.json()["avatar_url"] is None


# ---------------------------------------------------------------- 头像上传
class _FakeStorage:
    """内存对象存储，便于断言写入 / 删除的 key"""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []

    def put(self, key, data, content_type="application/octet-stream"):
        self.objects[key] = data
        return {"etag": key, "size": len(data)}

    def get(self, key):
        return self.objects[key]

    def delete(self, key):
        self.deleted.append(key)
        self.objects.pop(key, None)

    def exists(self, key):
        return key in self.objects


@pytest.fixture
def fake_storage(monkeypatch):
    from app.services import avatars

    store = _FakeStorage()
    monkeypatch.setattr(avatars, "get_storage", lambda: store)
    return store


def _png_bytes(size: tuple[int, int] = (800, 600)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 80, 60)).save(buf, format="PNG")
    return buf.getvalue()


def _auth_headers(client, email_capture, name: str) -> dict[str, str]:
    _register_verified(client, email_capture, name, f"{name}@example.com")
    login = client.post(PREFIX + "/login", json={"account": name, "password": "Passw0rd!"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_upload_avatar_normalizes_and_serves(client, email_capture, fake_storage):
    headers = _auth_headers(client, email_capture, "avatar_user")

    resp = client.post(
        PREFIX + "/me/avatar",
        headers=headers,
        files={"file": ("me.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code == 200, resp.text
    avatar_url = resp.json()["avatar_url"]
    assert avatar_url.startswith("/api/v1/auth/avatar/")
    assert "?v=" in avatar_url

    # 对象已写入，内容是统一后的 256×256 JPEG
    assert len(fake_storage.objects) == 1
    key = next(iter(fake_storage.objects))
    with Image.open(io.BytesIO(fake_storage.objects[key])) as saved:
        assert saved.format == "JPEG"
        assert saved.size == (256, 256)

    # 公开路由直接返回图片字节
    image = client.get(avatar_url)
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/jpeg"
    assert image.headers["cache-control"] == "public, max-age=600"


def test_upload_avatar_rejects_invalid_input(client, email_capture, fake_storage):
    headers = _auth_headers(client, email_capture, "avatar_bad")

    not_image = client.post(
        PREFIX + "/me/avatar",
        headers=headers,
        files={"file": ("a.txt", b"not an image", "text/plain")},
    )
    assert not_image.status_code == 400
    assert "PNG" in not_image.json()["error"]["message"]

    gif = io.BytesIO()
    Image.new("RGB", (10, 10), (0, 0, 0)).save(gif, format="GIF")
    unsupported = client.post(
        PREFIX + "/me/avatar",
        headers=headers,
        files={"file": ("a.gif", gif.getvalue(), "image/gif")},
    )
    assert unsupported.status_code == 400

    too_large = client.post(
        PREFIX + "/me/avatar",
        headers=headers,
        files={"file": ("big.png", b"0" * (2 * 1024 * 1024 + 1), "image/png")},
    )
    assert too_large.status_code == 400
    assert "2MB" in too_large.json()["error"]["message"]

    assert fake_storage.objects == {}


def test_replace_avatar_cleans_old_object(client, email_capture, fake_storage):
    headers = _auth_headers(client, email_capture, "avatar_replace")

    first = client.post(
        PREFIX + "/me/avatar",
        headers=headers,
        files={"file": ("one.png", _png_bytes((400, 400)), "image/png")},
    )
    assert first.status_code == 200
    old_key = next(iter(fake_storage.objects))

    second = client.post(
        PREFIX + "/me/avatar",
        headers=headers,
        files={"file": ("two.png", _png_bytes((300, 500)), "image/png")},
    )
    assert second.status_code == 200
    assert first.json()["avatar_url"] != second.json()["avatar_url"]
    # 旧对象被删除，只剩新对象
    assert old_key not in fake_storage.objects
    assert old_key in fake_storage.deleted
    assert len(fake_storage.objects) == 1


def test_delete_avatar(client, email_capture, fake_storage):
    headers = _auth_headers(client, email_capture, "avatar_delete")

    uploaded = client.post(
        PREFIX + "/me/avatar",
        headers=headers,
        files={"file": ("me.png", _png_bytes(), "image/png")},
    )
    avatar_url = uploaded.json()["avatar_url"]
    key = next(iter(fake_storage.objects))

    removed = client.delete(PREFIX + "/me/avatar", headers=headers)
    assert removed.status_code == 200
    assert removed.json()["avatar_url"] is None
    assert key in fake_storage.deleted
    assert fake_storage.objects == {}
    assert client.get(avatar_url).status_code == 404

