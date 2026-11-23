"""人岗匹配引擎测试：特征归一、罚分、权重、经验差、理由、缓存复用"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.tenant import reset_company_id, set_company_id
from app.models.base import utcnow  # noqa: F401  （确保模型模块已加载）
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.match_result import MatchResult
from app.services.explain import build_template_explanation
from app.services.match_features import MatchFeatures, extract_features
from app.services.matching import _fingerprint, match_job
from app.services.scorer import compute_scores


def _skill(skill_id: int, name: str, display_name: str | None = None, aliases=None):
    return SimpleNamespace(
        id=skill_id, name=name, display_name=display_name, aliases=aliases or []
    )


def _job(**overrides):
    base = dict(
        title="Python 后端工程师",
        must_have_skills=[],
        skills=[],
        min_years=None,
        education_level=None,
        location=None,
        salary_min=None,
        salary_max=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _candidate(**overrides):
    base = dict(
        name="张三",
        skills=[],
        years_experience=None,
        education_level=None,
        city=None,
        current_title=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------- 特征提取
def test_must_and_nice_split_without_duplicates():
    """job.skills 含必备技能时不能重复计入加分技能"""
    skills = {
        1: _skill(1, "Python"),
        9: _skill(9, "FastAPI"),
        18: _skill(18, "PostgreSQL"),
        20: _skill(20, "Redis"),
    }
    job = _job(must_have_skills=[1, 9, 18], skills=[1, 9, 18, 20])
    cand = _candidate(skills=["Python", "FastAPI", "PostgreSQL", "Redis"])

    feats = extract_features(job, cand, skills)

    assert feats.must_skill_names == ["Python", "FastAPI", "PostgreSQL"]
    assert feats.nice_skill_names == ["Redis"]
    assert feats.matched_must == ["Python", "FastAPI", "PostgreSQL"]
    assert feats.matched_nice == ["Redis"]
    assert len(feats.matched_must + feats.matched_nice) == 4


def test_skill_matches_display_name_and_version_suffix():
    """展示名（RAG/检索增强生成）与版本号（Vue3/Vue）都要能命中"""
    skills = {
        13: _skill(13, "Vue", "Vue"),
        39: _skill(39, "RAG", "检索增强生成"),
        40: _skill(40, "LLM", "大语言模型"),
    }
    job = _job(must_have_skills=[39], skills=[13, 40])
    cand = _candidate(skills=["Vue3", "RAG", "LLM"])

    feats = extract_features(job, cand, skills)

    assert feats.matched_must == ["检索增强生成"]
    assert feats.matched_nice == ["Vue", "大语言模型"]
    assert feats.missing_must == []


# ---------------------------------------------------------------- 规则打分
def test_missing_must_skill_applies_penalty():
    """缺任一必备技能：技能分整体 ×0.6"""
    feats = MatchFeatures(
        must_skill_names=["A", "B"],
        matched_must=["A"],
        nice_skill_names=["C", "D"],
        matched_nice=["C", "D"],
    )
    scores = compute_scores(feats)

    # (0.7 * 0.5 + 0.3 * 1.0) * 0.6 = 0.39
    assert scores["skill_score"] == 0.39


def test_full_match_scores_near_100():
    """必备/加分全命中、年限达标、学历满足、地点匹配时接近满分"""
    feats = MatchFeatures(
        must_skill_names=["A", "B"],
        matched_must=["A", "B"],
        nice_skill_names=["C"],
        matched_nice=["C"],
        jd_min_years=3.0,
        candidate_years=3.0,
        years_gap=0.0,
        jd_edu_level="bachelor",
        candidate_edu_level="bachelor",
        location_match=True,
    )
    scores = compute_scores(feats)

    assert scores["skill_score"] == 1.0
    assert scores["exp_score"] == 0.7
    assert scores["edu_score"] == 1.0
    # 地点满分、薪资未限制、行业无数据给中性分 → 其他分 0.94
    assert scores["score"] >= 90.0


def test_experience_gap_is_linear_and_has_floor():
    """缺 1.5 年 / 要求 3 年：年限分 0.6 × 0.5"""
    feats = MatchFeatures(
        jd_min_years=3.0,
        candidate_years=1.5,
        years_gap=-1.5,
        jd_edu_level=None,
    )
    scores = compute_scores(feats)
    assert scores["exp_score"] == 0.4  # 0.3 年限 + 0.1 稳定性

    feats_no_year = MatchFeatures(jd_min_years=3.0, candidate_years=0.0, years_gap=-3.0)
    assert compute_scores(feats_no_year)["exp_score"] == 0.0


def test_education_meet_over_and_below():
    assert compute_scores(
        MatchFeatures(jd_edu_level="bachelor", candidate_edu_level="bachelor")
    )["edu_score"] == 1.0
    assert compute_scores(
        MatchFeatures(jd_edu_level="bachelor", candidate_edu_level="master")
    )["edu_score"] == 0.9
    assert compute_scores(
        MatchFeatures(jd_edu_level="master", candidate_edu_level="bachelor")
    )["edu_score"] == 0.5


def test_relevance_uses_title_tokens_not_single_chars():
    """职位名相关度按词元计算：后端工程师 → 高级后端工程师 有加分"""
    feats = MatchFeatures(
        jd_min_years=1.0,
        candidate_years=3.0,
        years_gap=2.0,
        job_title="Python 后端工程师",
        candidate_current_title="高级后端工程师",
    )
    assert compute_scores(feats)["exp_score"] > 0.7


# ---------------------------------------------------------------- 理由与指纹
def test_explanation_contains_hit_miss_and_years_gap():
    feats = MatchFeatures(
        must_skill_names=["Python", "PostgreSQL"],
        matched_must=["Python"],
        missing_must=["PostgreSQL"],
        jd_min_years=3.0,
        candidate_years=1.5,
        years_gap=-1.5,
        jd_edu_level="bachelor",
        candidate_edu_level="bachelor",
    )
    scores = compute_scores(feats)
    explanation = build_template_explanation(feats, scores)

    assert "命中 1 项" in explanation["summary"]
    assert "缺 1 项" in explanation["summary"]
    assert "经验差 1.5 年" in explanation["summary"]
    assert "PostgreSQL" in explanation["missing_skills"][0]
    assert explanation["risks"]


def test_fingerprint_changes_with_jd_version_or_resume_hash():
    assert _fingerprint(1, "abc") == _fingerprint(1, "abc")
    assert _fingerprint(1, "abc") != _fingerprint(2, "abc")
    assert _fingerprint(1, "abc") != _fingerprint(1, "def")


# ---------------------------------------------------------------- 缓存复用
def _run_cache_scenario(db_path: str) -> tuple[int, int, int, int, int]:
    async def scenario():
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(
            engine, expire_on_commit=False, autoflush=False
        )
        try:
            async with session_factory() as db:
                set_company_id(1)
                job = Job(
                    title="Python 后端工程师",
                    must_have_skills=[],
                    skills=[],
                    status="published",
                    company_id=1,
                )
                cand1 = Candidate(
                    name="张三",
                    dedupe_key="phone:1",
                    skills=["Python"],
                    years_experience=2,
                    education_level="bachelor",
                    city="上海",
                    company_id=1,
                )
                cand2 = Candidate(
                    name="李四",
                    dedupe_key="phone:2",
                    skills=["Java"],
                    years_experience=1,
                    education_level="bachelor",
                    city="北京",
                    company_id=1,
                )
                db.add_all([job, cand1, cand2])
                await db.commit()

                first = await match_job(db, job)
                second = await match_job(db, job)
                rows_before = await db.scalar(
                    select(func.count()).select_from(MatchResult)
                )

                job.jd_version += 1
                await db.commit()
                third = await match_job(db, job)
                rows_after = await db.scalar(
                    select(func.count()).select_from(MatchResult)
                )
                return (
                    first.computed_count,
                    second.cached_count,
                    second.computed_count,
                    rows_before or 0,
                    rows_after or 0,
                )
        finally:
            reset_company_id()
            await engine.dispose()

    return asyncio.run(scenario())


def test_match_job_reuses_cache_and_cleans_stale_rows(tmp_path):
    computed_1, cached_2, computed_2, rows_before, rows_after = _run_cache_scenario(
        str(tmp_path / "matching.db")
    )

    assert computed_1 == 2           # 首次全量计算
    assert cached_2 == 2             # 第二次全部命中缓存
    assert computed_2 == 0           # 不重复计算
    assert rows_before == 2          # 一人一条，没有重复
    assert rows_after == 2           # JD 版本变化后旧指纹被清理
