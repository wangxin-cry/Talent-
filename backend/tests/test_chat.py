"""阶段九½：对话式入口测试

覆盖：
- 20 条典型话术路由 ≥ 16 条
- 缺参追问一次 + 补参后继续执行
- 不可逆操作 100% 先确认（状态未变 → 确认后变更）
- 会话持久化 / 卡片结构化
- AI（LLM）不可用时仍可用
"""
from __future__ import annotations

PREFIX = "/api/v1"


_SHARED_HEADERS: dict[str, str] | None = None


def _register_user(client, email_capture, name: str) -> dict[str, str]:
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


def _auth_headers(client, email_capture, suffix: str) -> dict[str, str]:
    """本文件共用一个账号，避免把管理员用户列表挤出默认分页"""
    global _SHARED_HEADERS
    if _SHARED_HEADERS is None:
        _SHARED_HEADERS = _register_user(client, email_capture, "chat_shared")
    return _SHARED_HEADERS


def _create_skill(client, headers, name: str) -> int:
    resp = client.post(
        f"{PREFIX}/skills",
        json={"name": name, "aliases": [], "category": "language"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_job(client, headers, title: str, skill_ids: list[int]) -> int:
    resp = client.post(
        f"{PREFIX}/jobs",
        json={
            "title": title,
            "department": "平台研发",
            "location": "上海",
            "description": "负责核心服务开发。",
            "requirements": "熟悉 Python/FastAPI。",
            "skills": skill_ids,
            "must_have_skills": skill_ids[:1],
            "min_years": 3,
            "education_level": "bachelor",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_candidate(
    client, headers, name: str, skills: list[str], years: float = 4
) -> int:
    resp = client.post(
        f"{PREFIX}/candidates",
        json={
            "name": name,
            "city": "上海",
            "education_level": "bachelor",
            "years_experience": years,
            "current_company": "某某科技",
            "current_title": "后端工程师",
            "skills": skills,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_application(client, headers, job_id: int, candidate_id: int) -> int:
    resp = client.post(
        f"{PREFIX}/applications",
        json={"job_id": job_id, "candidate_id": candidate_id, "source": "manual"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_session(
    client,
    headers,
    *,
    job_id: int | None = None,
    candidate_id: int | None = None,
) -> int:
    resp = client.post(
        f"{PREFIX}/chat/sessions",
        json={
            "title": "测试会话",
            "context_job_id": job_id,
            "context_candidate_id": candidate_id,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _send(client, headers, session_id: int, text: str, **kwargs) -> dict:
    resp = client.post(
        f"{PREFIX}/chat/sessions/{session_id}/messages",
        json={"text": text, **kwargs},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------- 意图路由
UTTERANCES = [
    ("我传了一批简历", "resume_upload"),
    ("上传简历", "resume_upload"),
    ("看看这批简历谁适合后端岗", "match"),
    ("这批人谁最适合后端岗", "match"),
    ("匹配一下", "match"),
    ("给前三个出面试题", "interview"),
    ("给张伟生成面试题", "interview"),
    ("把张伟推到面试", "advance_status"),
    ("张伟现在什么状态", "application_status"),
    ("这个月哪个渠道效率最高", "analytics"),
    ("本月招聘数据怎么样", "analytics"),
    ("帮我把这个月的看板数据拿出来", "analytics"),
    ("帮我写一个 Python 后端工程师的 JD", "jd_generate"),
    ("生成 JD", "jd_generate"),
    ("淘汰王强，简历都没解析出来", "reject_candidate"),
    ("发布这个职位", "publish_job"),
    ("从人才库找找会 Go 的、5 年以上的", "search_candidates"),
    ("找找会 Python 的候选人", "search_candidates"),
    ("这个候选人流程走到哪一步了", "application_status"),
    ("安排张伟下周面试", "advance_status"),
]


def test_twenty_utterances_route_at_least_sixteen():
    from app.chat.nlu import classify_intent

    hits = 0
    misses: list[tuple[str, str | None, str]] = []
    for text, expected in UTTERANCES:
        actual, _ = classify_intent(text)
        if actual == expected:
            hits += 1
        else:
            misses.append((text, actual, expected))
    assert hits >= 19, f"只命中 {hits}/20：{misses}"


def test_word_order_variants_route_correctly():
    """词序变化也要能识别（如「把职位上架」vs「上架职位」）"""
    from app.chat.nlu import classify_intent

    cases = [
        ("把职位上架", "publish_job"),
        ("职位发布出去", "publish_job"),
        ("开放这个职位", "publish_job"),
        ("给候选人排个序", "match"),
        ("有哪些会 Go 的候选人", "search_candidates"),
    ]
    for text, expected in cases:
        actual, _ = classify_intent(text)
        assert actual == expected, f"{text!r} 期望 {expected}，实际 {actual}"


def test_ambiguous_utterances_do_not_guess():
    from app.chat.nlu import classify_intent

    for text in ("帮我看看", "继续", "处理一下"):
        intent, _ = classify_intent(text)
        assert intent is None, f"{text} 不应被强行路由：{intent}"


# ---------------------------------------------------------------- 工具注册表
def test_tool_registry_has_levels_and_schema(client, email_capture):
    headers = _auth_headers(client, email_capture, "tools")
    resp = client.get(f"{PREFIX}/chat/tools", headers=headers)
    assert resp.status_code == 200, resp.text
    tools = {item["name"]: item for item in resp.json()["items"]}
    assert {
        "parse_resume",
        "search_candidates",
        "match_job",
        "generate_interview",
        "advance_status",
        "reject_candidate",
        "publish_job",
        "query_analytics",
    } <= set(tools)
    assert tools["match_job"]["level"] == "read"
    assert tools["publish_job"]["level"] == "write"
    assert tools["advance_status"]["level"] == "irreversible"
    assert tools["match_job"]["parameters"]["required"] == ["job_id"]


# ---------------------------------------------------------------- 会话与卡片
def test_session_persists_messages_and_chart_card(client, email_capture):
    headers = _auth_headers(client, email_capture, "session")
    session_id = _create_session(client, headers)

    data = _send(client, headers, session_id, "这个月哪个渠道效率最高？")
    assert data["intent"] == "analytics"
    assert data["replies"], data
    card = data["replies"][0]
    assert card["card_type"] == "chart"
    assert "channels" in card["card_data"]

    detail = client.get(f"{PREFIX}/chat/sessions/{session_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]
    assert "channels" in body["messages"][1]["card_data"]

    listing = client.get(f"{PREFIX}/chat/sessions", headers=headers)
    assert listing.status_code == 200
    item = next(row for row in listing.json()["items"] if row["id"] == session_id)
    assert item["message_count"] == 2
    assert item["last_message"] == card["content"]


def test_empty_session_hidden_by_default(client, email_capture):
    """新建但没发消息的空会话不该出现在侧栏列表里"""
    headers = _auth_headers(client, email_capture, "emptysess")
    empty_id = _create_session(client, headers)

    default_list = client.get(f"{PREFIX}/chat/sessions", headers=headers).json()["items"]
    assert all(row["id"] != empty_id for row in default_list), "空会话不应默认出现"

    with_empty = client.get(
        f"{PREFIX}/chat/sessions", headers=headers, params={"include_empty": "true"}
    ).json()["items"]
    assert any(row["id"] == empty_id for row in with_empty), "include_empty=true 时应出现"

    # 发一条消息后就进入列表
    _send(client, headers, empty_id, "这个月哪个渠道效率最高？")
    after = client.get(f"{PREFIX}/chat/sessions", headers=headers).json()["items"]
    assert any(row["id"] == empty_id for row in after)


# ---------------------------------------------------------------- 缺参追问
def test_missing_job_asks_once_then_accepts_follow_up(client, email_capture):
    headers = _auth_headers(client, email_capture, "clarify")
    python_id = _create_skill(client, headers, "PythonChatClarify")
    job_id = _create_job(client, headers, "对话追问后端工程师", [python_id])
    candidate_id = _create_candidate(
        client, headers, "追问候选人甲", ["PythonChatClarify"]
    )
    _create_application(client, headers, job_id, candidate_id)

    session_id = _create_session(client, headers)

    first = _send(client, headers, session_id, "匹配一下")
    assert first["needs_clarification"] is True
    assert "哪个职位" in first["replies"][0]["content"]
    clarify = first["replies"][0]["card_data"]["clarify"]
    assert clarify["field"] == "job"
    assert clarify["resolved"] is False

    # 补齐职位后继续执行，而不是重复追问
    second = _send(client, headers, session_id, "对话追问后端工程师")
    assert second["needs_clarification"] is False
    assert second["intent"] == "match"
    assert second["replies"][0]["card_type"] == "match_rank"


def test_clarification_is_not_repeated_forever(client, email_capture):
    headers = _auth_headers(client, email_capture, "once")
    session_id = _create_session(client, headers)

    first = _send(client, headers, session_id, "匹配一下")
    assert first["needs_clarification"] is True
    second = _send(client, headers, session_id, "匹配一下")
    assert second["needs_clarification"] is False, second
    assert "我可以帮你" in second["replies"][0]["content"]


def test_switching_intent_during_clarification_is_respected(client, email_capture):
    """
    回归：追问状态下用户改聊别的，新意图必须被执行

    早期实现用 pending_failed 一刀切：只要上一轮追问没补上，
    新请求即使能被识别也会被吞成 intent=None，回一句能力清单，
    用户会觉得"说了半天没反应"。
    """
    headers = _auth_headers(client, email_capture, "switchintent")
    session_id = _create_session(client, headers)

    first = _send(client, headers, session_id, "把职位上架")
    assert first["intent"] == "publish_job"
    assert first["needs_clarification"] is True

    # 不回答职位，改问匹配：应识别为 match 并再次追问职位（新请求），而不是能力清单
    second = _send(client, headers, session_id, "给候选人排个序")
    assert second["intent"] == "match", second
    assert second["needs_clarification"] is True, "match 缺职位应追问"
    question = second["replies"][0].get("content") or ""
    assert "职位" in question


# ---------------------------------------------------------------- 不可逆确认
def test_irreversible_advance_requires_confirmation(client, email_capture):
    headers = _auth_headers(client, email_capture, "confirm")
    skill_id = _create_skill(client, headers, "PythonChatConfirm")
    job_id = _create_job(client, headers, "对话确认后端工程师", [skill_id])
    candidate_id = _create_candidate(
        client, headers, "确认候选人乙", ["PythonChatConfirm"]
    )
    application_id = _create_application(client, headers, job_id, candidate_id)

    session_id = _create_session(
        client, headers, job_id=job_id, candidate_id=candidate_id
    )

    def _send_and_confirm(text: str) -> dict:
        data = _send(client, headers, session_id, text)
        confirm = data["replies"][0]
        assert confirm["card_type"] == "confirm", data
        assert confirm["card_data"]["status"] == "pending"
        resp = client.post(
            f"{PREFIX}/chat/sessions/{session_id}/confirm",
            json={"message_id": confirm["id"]},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert "已更新" in resp.json()["message"]["content"]
        return data

    # 状态机要求逐级推进：new → screening → interview
    data = _send_and_confirm("把确认候选人乙推进到筛选中")
    assert data["intent"] == "advance_status"
    assert data["replies"][0]["card_data"]["to_status"] == "screening"

    board = client.get(
        f"{PREFIX}/applications/board", params={"job_id": job_id}, headers=headers
    )
    assert board.status_code == 200, board.text
    statuses = {
        item["id"]: item["status"]
        for column in board.json()["columns"]
        for item in column["items"]
    }
    assert statuses[application_id] == "screening"

    # 未确认前状态不变
    pending = _send(client, headers, session_id, "把确认候选人乙推到面试")
    confirm = pending["replies"][0]
    assert confirm["card_type"] == "confirm"
    assert confirm["card_data"]["to_status"] == "interview"
    board = client.get(
        f"{PREFIX}/applications/board", params={"job_id": job_id}, headers=headers
    )
    statuses = {
        item["id"]: item["status"]
        for column in board.json()["columns"]
        for item in column["items"]
    }
    assert statuses[application_id] == "screening"

    confirmed = client.post(
        f"{PREFIX}/chat/sessions/{session_id}/confirm",
        json={"message_id": confirm["id"]},
        headers=headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    assert "已更新" in confirmed.json()["message"]["content"]

    board = client.get(
        f"{PREFIX}/applications/board", params={"job_id": job_id}, headers=headers
    )
    statuses = {
        item["id"]: item["status"]
        for column in board.json()["columns"]
        for item in column["items"]
    }
    assert statuses[application_id] == "interview"


def test_reject_requires_reason_and_confirm(client, email_capture):
    headers = _auth_headers(client, email_capture, "reject")
    skill_id = _create_skill(client, headers, "PythonChatReject")
    job_id = _create_job(client, headers, "对话淘汰后端工程师", [skill_id])
    candidate_id = _create_candidate(
        client, headers, "淘汰候选人丙", ["PythonChatReject"]
    )
    application_id = _create_application(client, headers, job_id, candidate_id)

    session_id = _create_session(
        client, headers, job_id=job_id, candidate_id=candidate_id
    )
    data = _send(client, headers, session_id, "淘汰淘汰候选人丙")
    confirm = data["replies"][0]
    assert confirm["card_type"] == "confirm"
    assert confirm["card_data"]["requires_reason"] is True

    missing_reason = client.post(
        f"{PREFIX}/chat/sessions/{session_id}/confirm",
        json={"message_id": confirm["id"]},
        headers=headers,
    )
    assert missing_reason.status_code == 400
    assert "原因" in missing_reason.json()["error"]["message"]

    ok = client.post(
        f"{PREFIX}/chat/sessions/{session_id}/confirm",
        json={"message_id": confirm["id"], "note": "简历信息不完整"},
        headers=headers,
    )
    assert ok.status_code == 200, ok.text
    assert "已更新" in ok.json()["message"]["content"]

    detail = client.get(f"{PREFIX}/applications/{application_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "rejected"


# ---------------------------------------------------------------- AI 不可用
def test_chat_works_when_llm_is_down(client, email_capture, monkeypatch):
    from app.core.config import settings
    from app.services import llm

    async def broken(*args, **kwargs):
        raise llm.LLMError("模拟模型不可用")

    monkeypatch.setattr(llm, "chat_json", broken)
    monkeypatch.setattr(settings, "LLM_MOCK", False)
    monkeypatch.setattr(settings, "SILICONFLOW_API_KEY", "test-key")
    monkeypatch.setattr(settings, "SILICONFLOW_BASE_URL", "http://127.0.0.1:1")

    headers = _auth_headers(client, email_capture, "noai")
    session_id = _create_session(client, headers)

    # 规则能覆盖的意图照常工作
    data = _send(client, headers, session_id, "这个月哪个渠道效率最高？")
    assert data["intent"] == "analytics"
    assert data["replies"][0]["card_type"] == "chart"

    # 规则覆盖不了时也不 500，而是退回能力清单
    fallback = _send(client, headers, session_id, "帮我看看")
    assert fallback["intent"] is None
    assert "我可以帮你" in fallback["replies"][0]["content"]


# ---------------------------------------------------------------- 流式（SSE）
def test_stream_endpoint_emits_progress_and_done(client, email_capture):
    import json

    headers = _auth_headers(client, email_capture, "stream")
    session_id = _create_session(client, headers)

    started = client.post(
        f"{PREFIX}/chat/sessions/{session_id}/messages/stream",
        json={"text": "这个月哪个渠道效率最高？"},
        headers=headers,
    )
    assert started.status_code == 202, started.text
    task_id = started.json()["task_id"]

    events: list[dict] = []
    with client.stream(
        "GET",
        f"{PREFIX}/chat/sessions/{session_id}/tasks/{task_id}/events",
        headers=headers,
    ) as response:
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

    types = [event["type"] for event in events]
    assert "status" in types, events
    assert "intent" in types, events
    assert "done" in types, events
    done = next(event for event in events if event["type"] == "done")
    assert done["replies"][0]["card_type"] == "chart"
    assert done["session"]["id"] == session_id

    # 任务结束后消息已落库，可回看
    detail = client.get(f"{PREFIX}/chat/sessions/{session_id}", headers=headers)
    assert detail.status_code == 200
    assert len(detail.json()["messages"]) == 2


def test_stream_task_is_private(client, email_capture):
    owner = _auth_headers(client, email_capture, "stream_owner")
    other = _register_user(client, email_capture, "chat_stream_other")
    session_id = _create_session(client, owner)

    started = client.post(
        f"{PREFIX}/chat/sessions/{session_id}/messages/stream",
        json={"text": "这个月哪个渠道效率最高？"},
        headers=owner,
    )
    task_id = started.json()["task_id"]

    denied = client.get(
        f"{PREFIX}/chat/sessions/{session_id}/tasks/{task_id}/events",
        headers=other,
    )
    assert denied.status_code == 404


# ---------------------------------------------------------------- 真实编排
def test_chat_runs_supervisor_and_links_trace(client, email_capture):
    from app.models.agent_trace import (
        AGENT_ANALYTICS,
        AGENT_INTERVIEW,
        AGENT_MATCH_ENGINE,
    )

    headers = _auth_headers(client, email_capture, "trace")
    skill_id = _create_skill(client, headers, "PythonChatTrace")
    job_id = _create_job(client, headers, "对话编排后端工程师", [skill_id])
    _create_candidate(client, headers, "编排候选人甲", ["PythonChatTrace"], years=6)
    _create_candidate(client, headers, "编排候选人乙", ["PythonChatTrace"], years=3)
    session_id = _create_session(client, headers, job_id=job_id)

    matched = _send(client, headers, session_id, "看看这批简历谁适合后端岗")
    assert matched["replies"][0]["card_type"] == "match_rank", matched
    trace_id = matched["trace_id"]
    assert trace_id
    assert matched["replies"][0]["trace_id"] == trace_id
    assert (matched["replies"][0]["card_data"]["total"] or 0) >= 2

    trace = client.get(f"{PREFIX}/orchestration/traces/{trace_id}", headers=headers)
    assert trace.status_code == 200, trace.text
    detail = trace.json()
    assert detail["intent"] == "match"
    agents = {step["agent"] for step in detail["steps"]}
    assert AGENT_MATCH_ENGINE in agents, detail
    assert all(step["duration_ms"] >= 0 for step in detail["steps"])

    # 面试题：full_eval = 匹配 + 逐人出题，必须能在同一条轨迹里看到两个子 Agent
    questions = _send(client, headers, session_id, "给前两个出面试题")
    cards = [item for item in questions["replies"] if item["card_type"] == "interview"]
    assert len(cards) >= 1, questions
    assert questions["trace_id"]
    trace = client.get(
        f"{PREFIX}/orchestration/traces/{questions['trace_id']}", headers=headers
    )
    assert trace.status_code == 200, trace.text
    agents = {step["agent"] for step in trace.json()["steps"]}
    assert {AGENT_MATCH_ENGINE, AGENT_INTERVIEW} <= agents, agents

    # 看板问答也走 Supervisor 的 AnalyticsAgent
    analytics = _send(client, headers, session_id, "这个月哪个渠道效率最高？")
    assert analytics["replies"][0]["card_type"] == "chart"
    trace = client.get(
        f"{PREFIX}/orchestration/traces/{analytics['trace_id']}", headers=headers
    )
    assert trace.status_code == 200, trace.text
    assert AGENT_ANALYTICS in {step["agent"] for step in trace.json()["steps"]}


# ---------------------------------------------------------------- 权限
def test_cannot_read_other_users_session(client, email_capture):
    owner = _auth_headers(client, email_capture, "owner")
    other = _register_user(client, email_capture, "chat_outsider")
    session_id = _create_session(client, owner)

    resp = client.get(f"{PREFIX}/chat/sessions/{session_id}", headers=other)
    assert resp.status_code == 404
