"""
阶段七：数据分析与成本监控测试

覆盖：
1. 漏斗口径 = 「到达过该阶段」而不是「当前停留」（防止漏斗不单调、转化率失真）
2. 概览指标与库一致（在招职位 / 投递数 / 待面试 / 周期）
3. 渠道统计（投递 / 到达面试 / 入学 / 淘汰）
4. 成本汇总与明细（金额按 token 单价计算）
5. 单价函数边界
"""
from __future__ import annotations

import os
import sqlite3

from app.core.pricing import estimate_cost, price_of
from app.models.base import utcnow

PREFIX = "/api/v1"


def _db_path() -> str:
    return os.environ["DATABASE_URL"].split("sqlite+aiosqlite:///", 1)[1]


def _auth(client, email_capture, suffix: str) -> dict[str, str]:
    name = f"stat_{suffix}"
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


def _job(client, headers, title: str = "数据分析测试岗") -> int:
    resp = client.post(
        f"{PREFIX}/jobs",
        json={
            "title": title,
            "department": "技术部",
            "location": "上海",
            "description": "用于分析测试的职位描述。",
            "requirements": "具备后端开发经验。",
            "skills": [],
            "must_have_skills": [],
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _candidate(client, headers, name: str) -> int:
    resp = client.post(
        f"{PREFIX}/candidates",
        json={"name": name, "city": "上海", "education_level": "bachelor"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _application(client, headers, job_id: int, candidate_id: int, source: str = "manual") -> int:
    resp = client.post(
        f"{PREFIX}/applications",
        json={"job_id": job_id, "candidate_id": candidate_id, "source": source},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _move(client, headers, application_id: int, target: str) -> None:
    resp = client.post(
        f"{PREFIX}/applications/{application_id}/transition",
        json={"to_status": target},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


def _insert_ai_call(
    *, feature: str, model: str, input_tokens: int, output_tokens: int, cost: float,
    job_id: int | None = None, status: str = "success",
) -> None:
    now = str(utcnow())
    conn = sqlite3.connect(_db_path())
    try:
        conn.execute(
            '''
            INSERT INTO ai_call
                (company_id, job_id, feature, provider, model,
                 input_tokens, output_tokens, total_tokens, cost, currency,
                 duration_ms, cache_hit, status, error_reason, trace_id, create_time)
            VALUES (1, ?, ?, 'siliconflow', ?, ?, ?, ?, ?, 'CNY',
                    1200, 0, ?, NULL, NULL, ?)
            ''',
            (
                job_id, feature, model, input_tokens, output_tokens,
                input_tokens + output_tokens, cost, status, now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------- 单价
def test_estimate_cost_uses_model_price():
    # deepseek-v4-flash: 输入 0.001 / 输出 0.002 元每 1K token
    assert price_of("deepseek-ai/DeepSeek-V4-Flash") == (0.001, 0.002)
    # 1000 输入 + 1000 输出 = 0.001 + 0.002
    assert estimate_cost("deepseek-ai/DeepSeek-V4-Flash", 1000, 1000) == 0.003
    # 未收录模型回落默认单价（>=0 即可）
    assert estimate_cost("unknown-model", 1000, 1000) >= 0


# ---------------------------------------------------------------- 漏斗
def test_funnel_counts_reached_not_current(client, email_capture):
    """漏斗必须按「到达过」统计：流转走的人仍计入上一阶段"""
    headers = _auth(client, email_capture, "funnel")
    job_id = _job(client, headers)

    a1 = _application(client, headers, job_id, _candidate(client, headers, "候选人A"))
    a2 = _application(client, headers, job_id, _candidate(client, headers, "候选人B"))
    a3 = _application(client, headers, job_id, _candidate(client, headers, "候选人C"))

    # A 停在 new；B 到 screening；C 到 interview
    _move(client, headers, a2, "screening")
    _move(client, headers, a3, "screening")
    _move(client, headers, a3, "interview")

    data = client.get(f"{PREFIX}/analytics/dashboard", headers=headers).json()
    funnel = {stage["status"]: stage for stage in data["funnel"]}

    assert funnel["new"]["count"] == 3          # 到达过 new 的 3 人
    assert funnel["screening"]["count"] == 2    # 到达过 screening 的 2 人
    assert funnel["interview"]["count"] == 1    # 到达过 interview 的 1 人

    # 当前停留口径单独给出，便于前端展示两种视角
    assert funnel["new"]["current"] == 1
    assert funnel["screening"]["current"] == 1
    assert funnel["interview"]["current"] == 1

    # 漏斗单调不增
    counts = [funnel[s]["count"] for s in ("new", "screening", "interview", "offer", "hired")]
    assert counts == sorted(counts, reverse=True), counts

    # 转化率相对上一阶段
    assert funnel["screening"]["conversion"] == round(2 / 3, 4)
    assert funnel["interview"]["conversion"] == round(1 / 2, 4)


def test_overview_matches_database(client, email_capture):
    headers = _auth(client, email_capture, "overview")
    job_id = _job(client, headers)
    for index in range(2):
        app_id = _application(
            client, headers, job_id, _candidate(client, headers, f"概览候选人{index}")
        )
        _move(client, headers, app_id, "screening")
        _move(client, headers, app_id, "interview")

    data = client.get(f"{PREFIX}/analytics/dashboard", headers=headers).json()
    overview = data["overview"]

    # 该职位是草稿，不计入"在招职位"
    assert overview["open_jobs"] == 0
    assert overview["total_applications"] >= 2
    assert overview["pending_interview"] >= 2
    assert overview["status_counts"].get("interview", 0) >= 2
    # 没有入职样本时平均周期为 None，不能编造成 0
    assert overview["avg_cycle_days"] is None


def test_channels_use_reached_interview(client, email_capture):
    """渠道的面试数按「到达过面试」统计，已入职的人也不能漏"""
    headers = _auth(client, email_capture, "channel")
    job_id = _job(client, headers)
    app_id = _application(
        client, headers, job_id, _candidate(client, headers, "渠道候选人"), source="referral"
    )
    _move(client, headers, app_id, "screening")
    _move(client, headers, app_id, "interview")
    _move(client, headers, app_id, "offer")
    _move(client, headers, app_id, "hired")

    data = client.get(f"{PREFIX}/analytics/dashboard", headers=headers).json()
    bucket = next(ch for ch in data["channels"] if ch["source"] == "referral")

    assert bucket["total"] >= 1
    assert bucket["interview"] >= 1      # 已经入职，但到达过面试
    assert bucket["hired"] >= 1
    assert 0 <= bucket["conversion"] <= 1


# ---------------------------------------------------------------- 成本
def test_cost_summary_and_list(client, email_capture):
    headers = _auth(client, email_capture, "cost")
    _insert_ai_call(
        feature="interview_generate",
        model="deepseek-ai/DeepSeek-V4-Flash",
        input_tokens=1000,
        output_tokens=500,
        cost=estimate_cost("deepseek-ai/DeepSeek-V4-Flash", 1000, 500),
    )

    summary = client.get(f"{PREFIX}/costs/summary", headers=headers).json()
    assert summary["total_calls"] >= 1
    assert summary["total_tokens"] >= 1500
    assert summary["total_cost"] > 0
    assert summary["budget"] > 0
    assert summary["budget_status"] in ("ok", "warning", "exceeded", "disabled")

    by_feature = {item["feature"]: item for item in summary["by_feature"]}
    assert "interview_generate" in by_feature
    assert by_feature["interview_generate"]["tokens"] >= 1500

    page = client.get(
        f"{PREFIX}/costs", headers=headers, params={"page": 1, "page_size": 5}
    ).json()
    assert page["total"] >= 1
    assert page["items"]
    item = page["items"][0]
    assert item["total_tokens"] == item["input_tokens"] + item["output_tokens"]
    assert item["cost"] >= 0


def test_cost_list_filter_by_feature(client, email_capture):
    headers = _auth(client, email_capture, "costfilter")
    _insert_ai_call(feature="resume_parse", model="deepseek-ai/DeepSeek-V4-Flash",
                    input_tokens=200, output_tokens=100, cost=0.0004)

    filtered = client.get(
        f"{PREFIX}/costs", headers=headers, params={"feature": "resume_parse"}
    ).json()
    assert filtered["total"] >= 1
    assert all(item["feature"] == "resume_parse" for item in filtered["items"])
