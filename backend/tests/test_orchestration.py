"""阶段九：多 Agent 编排测试

覆盖：
- 意图映射表
- 场景 B：一键评估 top3（排名 + 3 人面试题 + 轨迹 + 总成本）
- 子 Agent 超时降级（整体仍返回其余结果并标 degraded）
- 场景 C：推进状态（非法迁移不抛 500）
- AgentTrace 落库与轨迹查询
"""
from __future__ import annotations

import asyncio

PREFIX = "/api/v1"


def _auth_headers(client, email_capture, suffix: str) -> dict[str, str]:
    name = f"orch_{suffix}"
    email = f"{name}@example.com"
    resp = client.post(
        f"{PREFIX}/auth/register",
        json={"name": name, "email": email, "password": "Passw0rd!"},
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


def _create_job(client, headers, must_ids: list[int], skill_ids: list[int]) -> int:
    resp = client.post(
        f"{PREFIX}/jobs",
        json={
            "title": "编排测试后端工程师",
            "department": "平台研发",
            "location": "上海",
            "description": "负责核心服务开发。",
            "requirements": "熟悉 Python/FastAPI。",
            "skills": skill_ids,
            "must_have_skills": must_ids,
            "min_years": 3,
            "education_level": "bachelor",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_candidate(client, headers, name: str, skills: list[str], years: float = 4) -> int:
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


def _setup_job(client, headers, suffix: str) -> tuple[int, list[int]]:
    python_id = _create_skill(client, headers, f"Python{suffix}")
    fastapi_id = _create_skill(client, headers, f"FastAPI{suffix}")
    job_id = _create_job(client, headers, [python_id], [python_id, fastapi_id])
    candidate_ids = [
        _create_candidate(client, headers, f"候选人{i}-{suffix}", ["Python", "FastAPI"], 3 + i)
        for i in range(3)
    ]
    return job_id, candidate_ids


def test_intent_table(client, email_capture):
    headers = _auth_headers(client, email_capture, "intents")
    resp = client.get(f"{PREFIX}/orchestration/intents", headers=headers)
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    intents = {item["intent"] for item in items}
    assert {"full_eval", "match", "interview", "advance_status", "resume_upload"} <= intents
    full = next(item for item in items if item["intent"] == "full_eval")
    assert full["agents"] == ["MatchEngine", "InterviewAssistant"]


def test_scenario_b_full_eval_returns_ranking_questions_trace_cost(client, email_capture):
    headers = _auth_headers(client, email_capture, "full")
    job_id, _ = _setup_job(client, headers, "full")

    resp = client.post(
        f"{PREFIX}/orchestration/run",
        json={"intent": "full_eval", "job_id": job_id, "top_n": 3, "use_llm": False},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # ① 排名
    ranking = data["result"]["ranking"]
    assert len(ranking) == 3, ranking
    assert all(item["candidate_id"] for item in ranking)

    # ② 3 人面试题
    evaluations = data["result"]["evaluations"]
    assert len(evaluations) == 3
    assert all(item["status"] == "success" for item in evaluations)
    assert all(len(item["questions"]) >= 5 for item in evaluations)

    # ③ 轨迹：Manager 计划 + MatchEngine + InterviewAssistant + Manager 聚合
    agents = [step["agent"] for step in data["steps"]]
    assert agents.count("Manager") == 2
    assert "MatchEngine" in agents
    assert "InterviewAssistant" in agents
    assert len(data["plan"]) == 2

    # ④ 总成本字段存在（模板模式为 0，但结构完整）
    assert data["total_cost"] >= 0
    assert data["total_tokens"] >= 0
    assert data["trace_id"]

    # 轨迹已落库，可再次查询
    detail = client.get(
        f"{PREFIX}/orchestration/traces/{data['trace_id']}", headers=headers
    )
    assert detail.status_code == 200, detail.text
    assert len(detail.json()["steps"]) == len(data["steps"])
    recent = client.get(f"{PREFIX}/orchestration/traces", headers=headers)
    assert recent.status_code == 200
    assert any(item["trace_id"] == data["trace_id"] for item in recent.json()["items"])


def test_subagent_timeout_degrades_but_returns_rest(client, email_capture, monkeypatch):
    headers = _auth_headers(client, email_capture, "timeout")
    job_id, _ = _setup_job(client, headers, "timeout")

    from app.agents import subagents

    async def slow_interview(db, ctx):
        await asyncio.sleep(5)

    monkeypatch.setattr(subagents, "run_interview_assistant", slow_interview)

    resp = client.post(
        f"{PREFIX}/orchestration/run",
        json={
            "intent": "full_eval",
            "job_id": job_id,
            "top_n": 3,
            "step_timeout": 2.0,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # 整体降级，但匹配排名仍返回
    assert data["degraded"] is True
    assert data["status"] == "degraded"
    assert len(data["result"]["ranking"]) == 3
    assert data["result"]["evaluations"] == []

    timeout_steps = [
        step for step in data["steps"] if step["agent"] == "InterviewAssistant"
    ]
    assert timeout_steps, data["steps"]
    assert timeout_steps[0]["status"] == "timeout"
    assert timeout_steps[0]["degraded"] is True
    assert "超时" in (timeout_steps[0]["error_reason"] or "")

    # 轨迹里也能看到降级
    detail = client.get(
        f"{PREFIX}/orchestration/traces/{data['trace_id']}", headers=headers
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["degraded"] is True
    assert any(step["status"] == "timeout" for step in body["steps"])


def test_dependency_missing_skips_downstream_agent(client, email_capture, monkeypatch):
    """三级降级：匹配失败且无缓存 → 面试题步骤 skipped，整体仍返回"""

    headers = _auth_headers(client, email_capture, "dep")
    job_id, _ = _setup_job(client, headers, "dep")

    from app.agents import subagents

    async def broken_match(db, ctx):
        raise RuntimeError("模拟匹配故障")

    monkeypatch.setattr(subagents, "run_match_engine", broken_match)

    resp = client.post(
        f"{PREFIX}/orchestration/run",
        json={"intent": "full_eval", "job_id": job_id, "top_n": 3},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["degraded"] is True
    assert data["result"]["ranking"] == []
    assert data["result"]["evaluations"] == []

    steps = {step["agent"]: step for step in data["steps"]}
    assert steps["MatchEngine"]["status"] == "failed"
    assert steps["InterviewAssistant"]["status"] == "skipped"
    assert steps["InterviewAssistant"]["degraded"] is True


def test_scenario_c_advance_status_and_illegal_transition(client, email_capture):
    headers = _auth_headers(client, email_capture, "advance")
    job_id, candidate_ids = _setup_job(client, headers, "advance")
    application = client.post(
        f"{PREFIX}/applications",
        json={"job_id": job_id, "candidate_id": candidate_ids[0], "source": "manual"},
        headers=headers,
    )
    assert application.status_code == 201, application.text
    application_id = application.json()["id"]

    ok = client.post(
        f"{PREFIX}/orchestration/run",
        json={
            "intent": "advance_status",
            "application_id": application_id,
            "to_status": "screening",
        },
        headers=headers,
    )
    assert ok.status_code == 200, ok.text
    ok_data = ok.json()
    assert ok_data["degraded"] is False
    assert ok_data["result"]["allowed"] is True
    assert ok_data["result"]["to_status"] == "screening"

    # screening → offer 非法：返回 allowed=false，而不是 500
    bad = client.post(
        f"{PREFIX}/orchestration/run",
        json={
            "intent": "advance_status",
            "application_id": application_id,
            "to_status": "offer",
        },
        headers=headers,
    )
    assert bad.status_code == 200, bad.text
    bad_data = bad.json()
    assert bad_data["degraded"] is True
    assert bad_data["result"]["allowed"] is False
    assert "状态非法" in bad_data["result"]["reason"]


def test_missing_required_param_returns_400(client, email_capture):
    headers = _auth_headers(client, email_capture, "bad")
    resp = client.post(
        f"{PREFIX}/orchestration/run",
        json={"intent": "full_eval"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "job_id" in resp.json()["error"]["message"]


# ---------------------------------------------------------------- 回归
def test_interview_with_missing_candidate_degrades(client, email_capture):
    """
    回归：候选人不存在时必须降级，而不是用空上下文生成通用模板题并伪装成功

    早期 _load_context_for 对不存在的候选人静默返回空 context，
    面试 Agent 照常出 8 道通用题、status=success，用户完全察觉不到传错了 id。
    """
    headers = _auth_headers(client, email_capture, "ghost")
    job_id, _ = _setup_job(client, headers, "ghost")

    resp = client.post(
        f"{PREFIX}/orchestration/run",
        json={
            "intent": "interview",
            "job_id": job_id,
            "candidate_id": 999_999,
            "use_llm": False,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["degraded"] is True
    assert data["status"] == "degraded"
    # 失败明细要保留（便于前端展示"哪个候选人没出题"），但题目必须为空
    evaluations = data["result"]["evaluations"]
    assert len(evaluations) == 1
    assert evaluations[0]["status"] == "failed"
    assert evaluations[0]["questions"] == []
    assert any("不存在" in (err or "") for err in data["result"]["errors"])

    step = next(step for step in data["steps"] if step["agent"] == "InterviewAssistant")
    assert step["degraded"] is True
    assert "不存在" in (step["error_reason"] or "")


def test_recent_traces_aggregate_degraded_and_duration(client, email_capture, monkeypatch):
    """
    回归：最近轨迹聚合

    历史缺陷：聚合用了 func.max(AgentTrace.degraded)。
    SQLite 恰好支持 max(0/1)，PostgreSQL 没有 max(boolean) 会直接 500，
    所以单靠 SQLite 测试无法发现——本用例额外做静态检查，防止改回该写法。
    """
    headers = _auth_headers(client, email_capture, "traceagg")
    job_id, candidate_ids = _setup_job(client, headers, "traceagg")

    # 一次正常编排
    ok = client.post(
        f"{PREFIX}/orchestration/run",
        json={"intent": "match", "job_id": job_id},
        headers=headers,
    )
    assert ok.status_code == 200
    ok_trace = ok.json()["trace_id"]

    # 一次降级编排（依赖缺失）
    from app.agents import subagents

    async def broken_match(db, ctx):
        raise RuntimeError("模拟匹配故障")

    monkeypatch.setattr(subagents, "run_match_engine", broken_match)
    bad = client.post(
        f"{PREFIX}/orchestration/run",
        json={"intent": "match", "job_id": job_id},
        headers=headers,
    )
    assert bad.status_code == 200
    bad_trace = bad.json()["trace_id"]

    recent = client.get(f"{PREFIX}/orchestration/traces", headers=headers, params={"limit": 20})
    assert recent.status_code == 200, recent.text
    items = {item["trace_id"]: item for item in recent.json()["items"]}

    assert ok_trace in items and bad_trace in items
    assert items[ok_trace]["degraded"] is False
    assert items[ok_trace]["status"] == "success"
    assert items[bad_trace]["degraded"] is True
    assert items[bad_trace]["status"] == "degraded"
    assert items[ok_trace]["step_count"] >= 3

    # 静态检查：聚合不得再出现 max(布尔列) 的写法
    import inspect

    from app.agents import supervisor

    source = inspect.getsource(supervisor.list_recent_traces)
    assert "max(AgentTrace.degraded)" not in source, (
        "PostgreSQL 不支持 max(boolean)，请用 CASE 转 0/1 再聚合"
    )
