"""面试安排 / 评估 / 公开投递 / SLA / 报表导出 / 限流（PRD RA-02、RA-04、IA-02、IA-03、CE-01、CE-02、DA-05、§8.3）"""
from __future__ import annotations

import os
import sqlite3
import uuid

from app.core.security import hash_password
from app.models.base import utcnow

PREFIX = "/api/v1"


def _db_path() -> str:
    return os.environ["DATABASE_URL"].split("sqlite+aiosqlite:///", 1)[1]


def _company_slug() -> str:
    conn = sqlite3.connect(_db_path())
    try:
        row = conn.execute("SELECT slug FROM company WHERE id = 1").fetchone()
    finally:
        conn.close()
    assert row is not None
    return row[0]


def _admin_headers(client, suffix: str) -> dict[str, str]:
    name = f"iv_{suffix}"
    now = str(utcnow())
    conn = sqlite3.connect(_db_path())
    try:
        conn.execute(
            '''
            INSERT INTO "user"
                (company_id, name, email, password, role, department, status, email_verified_at,
                 login_fail_count, token_version, create_time, update_time)
            VALUES (1, ?, ?, ?, 'admin', 'HR', 'active', ?, 0, 0, ?, ?)
            ''',
            (name, f"{name}@example.com", hash_password("Passw0rd!"), now, now, now),
        )
        conn.commit()
    finally:
        conn.close()
    resp = client.post(f"{PREFIX}/auth/login", json={"account": name, "password": "Passw0rd!"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _published_job(client, headers) -> int:
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
            "title": f"后端工程师 {uuid.uuid4().hex[:4]}",
            "department": "平台研发",
            "location": "上海",
            "description": "负责核心服务研发。",
            "requirements": "熟悉 Python。",
            "skills": [skill.json()["id"]],
        },
    )
    assert job.status_code == 201, job.text
    job_id = job.json()["id"]
    published = client.post(f"{PREFIX}/jobs/{job_id}/publish", headers=headers)
    assert published.status_code == 200, published.text
    return job_id


def _apply(client, job_id: int, email: str) -> dict:
    response = client.post(
        f"{PREFIX}/public/applications",
        data={
            "company_slug": _company_slug(),
            "job_id": str(job_id),
            "name": "公开投递者",
            "email": email,
            "phone": "13800138001",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_public_job_apply_and_progress(client):
    headers = _admin_headers(client, "public")
    job_id = _published_job(client, headers)

    jobs = client.get(f"{PREFIX}/public/jobs", params={"slug": _company_slug()})
    assert jobs.status_code == 200
    assert any(item["id"] == job_id for item in jobs.json()["items"])
    detail = client.get(
        f"{PREFIX}/public/jobs/{job_id}", params={"slug": _company_slug()}
    )
    assert detail.status_code == 200
    assert detail.json()["title"].startswith("后端工程师")

    applied = _apply(client, job_id, "public_user@example.com")
    token = applied["tracking_token"]
    assert token

    # 重复投递幂等：同一个 token
    again = _apply(client, job_id, "public_user@example.com")
    assert again["tracking_token"] == token

    progress = client.get(
        f"{PREFIX}/public/applications/status",
        params={"token": token, "email": "public_user@example.com"},
    )
    assert progress.status_code == 200, progress.text
    payload = progress.json()
    assert payload["status"] == "new"
    assert payload["steps"][0]["label"] == "已投递"
    assert payload["steps"][0]["reached"] is True

    # 邮箱不匹配 -> 403
    wrong = client.get(
        f"{PREFIX}/public/applications/status",
        params={"token": token, "email": "other@example.com"},
    )
    assert wrong.status_code == 403


def test_interview_schedule_ics_and_feedback(client):
    headers = _admin_headers(client, "interview")
    job_id = _published_job(client, headers)
    applied = _apply(client, job_id, f"iv_{uuid.uuid4().hex[:6]}@example.com")
    application_id = applied["application_id"]

    schedule = client.put(
        f"{PREFIX}/applications/{application_id}/interview-schedule",
        headers=headers,
        json={
            "scheduled_at": "2026-12-01T06:30:00",
            "duration_minutes": 45,
            "mode": "online",
            "location": "https://meeting.example.com/x",
            "interviewer": "李面试官",
        },
    )
    assert schedule.status_code == 200, schedule.text
    assert schedule.json()["mode"] == "online"

    fetched = client.get(
        f"{PREFIX}/applications/{application_id}/interview-schedule", headers=headers
    )
    assert fetched.status_code == 200
    assert fetched.json()["duration_minutes"] == 45

    ics = client.get(f"{PREFIX}/applications/{application_id}/interview.ics", headers=headers)
    assert ics.status_code == 200
    assert "BEGIN:VCALENDAR" in ics.text
    assert "DTSTART:20261201T063000Z" in ics.text
    assert "text/calendar" in ics.headers["content-type"]

    template = client.get(f"{PREFIX}/interviews/evaluation-template", headers=headers)
    assert template.status_code == 200
    assert len(template.json()["dimensions"]) == 6

    feedback = client.post(
        f"{PREFIX}/applications/{application_id}/feedbacks",
        headers=headers,
        json={
            "round": 1,
            "scores": {"professional": 5, "communication": 4},
            "recommendation": "hire",
            "comment": "基础扎实",
        },
    )
    assert feedback.status_code == 201, feedback.text
    assert feedback.json()["overall_rating"] == 4.5

    summary = client.get(f"{PREFIX}/applications/{application_id}/feedbacks", headers=headers)
    assert summary.status_code == 200
    assert summary.json()["total"] == 1
    assert summary.json()["recommendation"] == "hire"


def test_sla_monitor_and_report_export(client, monkeypatch):
    from app.core.config import settings

    headers = _admin_headers(client, "sla")
    job_id = _published_job(client, headers)
    _apply(client, job_id, f"sla_{uuid.uuid4().hex[:6]}@example.com")

    # 阈值设为 0：刚投递也算超时，验证计算链路
    monkeypatch.setattr(settings, "SLA_HOURS_NEW", 0)
    sla = client.get(f"{PREFIX}/analytics/sla", headers=headers)
    assert sla.status_code == 200, sla.text
    payload = sla.json()
    assert payload["total"] >= 1
    assert payload["items"][0]["status"] == "new"
    assert payload["items"][0]["overdue_hours"] >= 0

    report = client.get(f"{PREFIX}/analytics/export", headers=headers)
    assert report.status_code == 200
    assert report.content[:2] == b"PK"  # xlsx 是 zip 容器
    assert "spreadsheetml" in report.headers["content-type"]


def test_sliding_window_limiter():
    from app.core.rate_limit import SlidingWindowLimiter

    limiter = SlidingWindowLimiter(limit=2, window_seconds=60)
    assert limiter.check("user:1", now=100.0)[0] is True
    assert limiter.check("user:1", now=101.0)[0] is True
    allowed, remaining, wait = limiter.check("user:1", now=102.0)
    assert allowed is False
    assert remaining == 0
    assert wait > 0
    # 其它用户不受影响
    assert limiter.check("user:2", now=102.0)[0] is True
    # 窗口滑过后恢复
    assert limiter.check("user:1", now=170.0)[0] is True
