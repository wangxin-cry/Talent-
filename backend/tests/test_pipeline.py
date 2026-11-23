"""招聘流程测试：状态机、流转历史、通知、看板、面试题引用与缓存"""
from __future__ import annotations

import json
import os
import sqlite3

from app.models.base import utcnow

PREFIX = "/api/v1"


def _db_path() -> str:
    return os.environ["DATABASE_URL"].split("sqlite+aiosqlite:///", 1)[1]


def _auth_headers(client, email_capture, suffix: str) -> dict[str, str]:
    name = f"pipe_{suffix}"
    email = f"{name}@example.com"
    resp = client.post(
        f"{PREFIX}/auth/register",
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
    assert client.post(f"{PREFIX}/auth/verify-email", json={"token": token}).status_code == 200
    login = client.post(
        f"{PREFIX}/auth/login", json={"account": name, "password": "Passw0rd!"}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_skill(client, headers, name: str) -> int:
    resp = client.post(
        f"{PREFIX}/skills",
        json={"name": name, "aliases": [], "category": "language"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_job(client, headers, *, must_ids: list[int], skill_ids: list[int]) -> int:
    resp = client.post(
        f"{PREFIX}/jobs",
        json={
            "title": "高级 Python 后端工程师",
            "department": "平台研发",
            "location": "上海",
            "description": "负责招聘平台核心服务的设计与开发。",
            "requirements": "熟悉 Python/FastAPI，有高并发系统设计经验。",
            "skills": skill_ids,
            "must_have_skills": must_ids,
            "min_years": 5,
            "education_level": "bachelor",
            "salary_min": 25,
            "salary_max": 40,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_candidate(client, headers, name: str, skills: list[str]) -> int:
    resp = client.post(
        f"{PREFIX}/candidates",
        json={
            "name": name,
            "city": "上海",
            "education_level": "bachelor",
            "years_experience": 3,
            "current_company": "某某科技",
            "current_title": "后端工程师",
            "skills": skills,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _insert_resume(candidate_id: int) -> None:
    structured = {
        "basic": {"name": "张三"},
        "education": [],
        "work": [{"company": "某某科技", "title": "后端工程师", "description": "负责订单系统"}],
        "projects": [
            {
                "name": "订单中台",
                "role": "后端负责人",
                "stack": ["Python", "FastAPI", "PostgreSQL", "Redis"],
                "description": "支撑日均百万订单的订单中台",
            },
            {
                "name": "实时风控",
                "role": "核心开发",
                "stack": ["Kafka", "Flink"],
                "description": "实时风控规则引擎",
            },
        ],
        "skills": ["Python", "FastAPI"],
        "certificates": [],
    }
    now = str(utcnow())
    conn = sqlite3.connect(_db_path())
    try:
        conn.execute(
            '''
            INSERT INTO resume
                (company_id, candidate_id, file_id, structured, field_confidence,
                 plain_text, parser_meta, content_hash, is_primary, version,
                 create_time, update_time)
            VALUES (1, ?, 0, ?, '{}', '', '{}', 'hash_pipeline_test', 1, 1, ?, ?)
            ''',
            (candidate_id, json.dumps(structured, ensure_ascii=False), now, now),
        )
        conn.commit()
    finally:
        conn.close()


def _create_application(client, headers, job_id: int, candidate_id: int) -> dict:
    resp = client.post(
        f"{PREFIX}/applications",
        json={"job_id": job_id, "candidate_id": candidate_id, "source": "manual"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _transition(client, headers, application_id: int, target: str, note: str | None = None):
    return client.post(
        f"{PREFIX}/applications/{application_id}/transition",
        json={"to_status": target, "note": note},
        headers=headers,
    )


def test_state_machine_history_and_notification(client, email_capture):
    headers = _auth_headers(client, email_capture, "flow")
    python_id = _create_skill(client, headers, "Python")
    k8s_id = _create_skill(client, headers, "Kubernetes")
    job_id = _create_job(client, headers, must_ids=[python_id, k8s_id], skill_ids=[python_id])
    candidate_id = _create_candidate(client, headers, "流程候选人", ["Python", "FastAPI"])
    _insert_resume(candidate_id)

    application = _create_application(client, headers, job_id, candidate_id)
    assert application["status"] == "new"
    assert application["allowed_next"] == ["rejected", "screening"]

    # 合法流转
    resp = _transition(client, headers, application["id"], "screening")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "screening"

    # 时间线：进入流程 + 状态变更
    timeline = client.get(
        f"{PREFIX}/applications/{application['id']}/timeline", headers=headers
    )
    assert timeline.status_code == 200, timeline.text
    items = timeline.json()["items"]
    assert len(items) == 2
    assert items[0]["from_status"] is None
    assert items[0]["to_status"] == "new"
    assert items[1]["from_status"] == "new"
    assert items[1]["to_status"] == "screening"
    assert items[1]["operator_name"] == "pipe_flow"

    # 状态变更触发站内通知
    notifications = client.get(f"{PREFIX}/notifications", headers=headers)
    assert notifications.status_code == 200, notifications.text
    payload = notifications.json()
    assert payload["unread"] >= 1
    related = [n for n in payload["items"] if n["application_id"] == application["id"]]
    assert len(related) == 1
    assert related[0]["template"] == "status_update"
    assert "流程候选人" in related[0]["body"]

    # 标记已读后未读数下降
    read = client.post(
        f"{PREFIX}/notifications/{related[0]['id']}/read", headers=headers
    )
    assert read.status_code == 200, read.text
    assert read.json()["status"] == "read"
    assert (
        client.get(f"{PREFIX}/notifications/unread-count", headers=headers).json()["unread"]
        == 0
    )


def test_illegal_transition_is_rejected(client, email_capture):
    headers = _auth_headers(client, email_capture, "illegal")
    skill_id = _create_skill(client, headers, "Go")
    job_id = _create_job(client, headers, must_ids=[skill_id], skill_ids=[skill_id])
    candidate_id = _create_candidate(client, headers, "跳级候选人", ["Go"])
    application = _create_application(client, headers, job_id, candidate_id)

    # new → offer 非法（不能跳级）
    resp = _transition(client, headers, application["id"], "offer")
    assert resp.status_code == 400
    assert "状态非法" in resp.json()["error"]["message"]

    detail = client.get(f"{PREFIX}/applications/{application['id']}", headers=headers)
    assert detail.json()["status"] == "new"

    # 未知状态
    resp = _transition(client, headers, application["id"], "ghost")
    assert resp.status_code == 400


def test_reject_requires_reason_and_is_terminal(client, email_capture):
    headers = _auth_headers(client, email_capture, "reject")
    skill_id = _create_skill(client, headers, "Java")
    job_id = _create_job(client, headers, must_ids=[skill_id], skill_ids=[skill_id])
    candidate_id = _create_candidate(client, headers, "淘汰候选人", ["Java"])
    application = _create_application(client, headers, job_id, candidate_id)

    # 淘汰必须填原因
    resp = _transition(client, headers, application["id"], "rejected")
    assert resp.status_code == 400
    assert "必须填写原因" in resp.json()["error"]["message"]

    resp = _transition(client, headers, application["id"], "rejected", note="技能不匹配")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "rejected"
    assert body["rejected_reason"] == "技能不匹配"
    assert body["allowed_next"] == []

    # 终态不可再流转
    resp = _transition(client, headers, application["id"], "screening")
    assert resp.status_code == 400


def test_board_columns_follow_status(client, email_capture):
    headers = _auth_headers(client, email_capture, "board")
    skill_id = _create_skill(client, headers, "C++")
    job_id = _create_job(client, headers, must_ids=[skill_id], skill_ids=[skill_id])
    candidate_id = _create_candidate(client, headers, "看板候选人", ["C++"])
    application = _create_application(client, headers, job_id, candidate_id)

    board = client.get(
        f"{PREFIX}/applications/board", params={"job_id": job_id}, headers=headers
    )
    assert board.status_code == 200, board.text
    data = board.json()
    assert [column["status"] for column in data["columns"]] == [
        "new",
        "screening",
        "interview",
        "offer",
        "hired",
        "rejected",
    ]
    new_column = next(column for column in data["columns"] if column["status"] == "new")
    assert any(item["id"] == application["id"] for item in new_column["items"])

    assert _transition(client, headers, application["id"], "screening").status_code == 200
    board = client.get(
        f"{PREFIX}/applications/board", params={"job_id": job_id}, headers=headers
    ).json()
    new_column = next(column for column in board["columns"] if column["status"] == "new")
    screening = next(column for column in board["columns"] if column["status"] == "screening")
    assert all(item["id"] != application["id"] for item in new_column["items"])
    assert any(item["id"] == application["id"] for item in screening["items"])


def test_questions_reference_experience_and_cache(client, email_capture):
    headers = _auth_headers(client, email_capture, "question")
    python_id = _create_skill(client, headers, "Python")
    k8s_id = _create_skill(client, headers, "Kubernetes")
    redis_id = _create_skill(client, headers, "Redis")
    job_id = _create_job(
        client, headers, must_ids=[python_id, k8s_id], skill_ids=[python_id, redis_id]
    )
    candidate_id = _create_candidate(client, headers, "面试题候选人", ["Python", "FastAPI"])
    _insert_resume(candidate_id)
    application = _create_application(client, headers, job_id, candidate_id)

    resp = client.post(
        f"{PREFIX}/applications/{application['id']}/questions",
        json={"use_llm": False},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    questions = data["questions"]
    assert 6 <= len(questions) <= 8
    assert data["cached"] is False
    assert data["source"] == "template"

    markers = ("项目：", "技能：", "经历：", "任职：", "缺口：")
    evidence = [
        q for q in questions if any(marker in (q["reference"] or "") for marker in markers)
    ]
    assert len(evidence) >= 5

    # 必须引用具体项目与缺口
    references = " ".join(q["reference"] or "" for q in questions)
    assert "订单中台" in references
    assert "Kubernetes" in references

    # 重复生成走缓存，不再产生新题目
    again = client.post(
        f"{PREFIX}/applications/{application['id']}/questions",
        json={"use_llm": False},
        headers=headers,
    )
    assert again.status_code == 200, again.text
    second = again.json()
    assert second["cached"] is True
    assert [q["id"] for q in second["questions"]] == [q["id"] for q in questions]

    listed = client.get(
        f"{PREFIX}/applications/{application['id']}/questions", headers=headers
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == len(questions)


def test_application_duplicate_is_rejected(client, email_capture):
    headers = _auth_headers(client, email_capture, "dup")
    skill_id = _create_skill(client, headers, "Rust")
    job_id = _create_job(client, headers, must_ids=[skill_id], skill_ids=[skill_id])
    candidate_id = _create_candidate(client, headers, "重复候选人", ["Rust"])
    _create_application(client, headers, job_id, candidate_id)

    resp = client.post(
        f"{PREFIX}/applications",
        json={"job_id": job_id, "candidate_id": candidate_id},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "已在" in resp.json()["error"]["message"]


def test_notification_requires_login(client):
    assert client.get(f"{PREFIX}/notifications").status_code == 401
