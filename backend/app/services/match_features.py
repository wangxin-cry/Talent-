"""
特征提取：把 JD 与候选人简历变成可直接打分的可比特征

输入：
- job（含 must_have_skills / skills 的 skill_id 数组、min_years、education_level、location、salary）
- candidate（含 skills 字符串数组、years_experience、education_level、city、structured）
- skill_map: {skill_id: Skill}，用于把 JD 的 skill_id 解析成标准名 / 别名

输出：MatchFeatures 数据类，各字段含义见注释。

两项关键约定：
1. job.skills 是「全部技能要求」，job.must_have_skills 是其子集；
   计算加分技能时必须先剔除必备技能，否则同一技能会被重复计分。
2. 技能匹配同时接受标准名、展示名与别名（如 RAG / 检索增强生成），
   并去掉技能名尾部的版本号（Vue3 -> Vue），避免同义技能漏命中。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from app.models.candidate import Candidate
from app.models.job import Job
from app.models.skill import Skill

# 技能名尾部版本号：Vue3 / Python3.11 / HTML5 -> Vue / Python / HTML
_VERSION_SUFFIX = re.compile(r"(?<=[a-z])\d+(?:\.\d+)*$")

_REMOTE_LOCATIONS = {"remote", "远程", "不限", "全国"}

@dataclass
class MatchFeatures:
    """一次人岗匹配的全部可比特征"""

    # ---- 技能 ----
    must_skill_names: list[str] = field(default_factory=list)   # JD 必备技能展示名
    nice_skill_names: list[str] = field(default_factory=list)   # JD 加分技能展示名（已剔除必备）
    candidate_skills: list[str] = field(default_factory=list)   # 候选人技能名

    matched_must: list[str] = field(default_factory=list)       # 命中的必备
    missing_must: list[str] = field(default_factory=list)       # 缺失的必备
    matched_nice: list[str] = field(default_factory=list)       # 命中的加分
    missing_nice: list[str] = field(default_factory=list)       # 缺失的加分

    # ---- 经验 ----
    jd_min_years: float | None = None
    candidate_years: float | None = None
    years_gap: float | None = None     # 候选人年限 - JD 最低要求（正=超，负=缺）

    # ---- 学历 ----
    jd_edu_level: str | None = None
    candidate_edu_level: str | None = None

    # ---- 其他 ----
    jd_location: str | None = None
    candidate_city: str | None = None
    location_match: bool = False

    jd_salary_min: int | None = None
    jd_salary_max: int | None = None

    # 原文辅助（LLM 理由用）
    candidate_name: str | None = None
    job_title: str | None = None
    candidate_current_title: str | None = None

def _to_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def _norm(text: str | None) -> str:
    """技能名归一：小写、去空格、去尾部版本号"""
    raw = (text or "").strip().casefold().replace(" ", "")
    return _VERSION_SUFFIX.sub("", raw)

def _skill_info(skill: Skill) -> tuple[str, set[str]]:
    """返回（展示名, 可接受的归一写法集合）"""
    label = skill.display_name or skill.name
    keys = {
        _norm(value)
        for value in (skill.name, skill.display_name, *(skill.aliases or []))
        if value
    }
    return label, keys

def _skill_pairs(
    ids: list[int] | None, skill_map: dict[int, Skill]
) -> list[tuple[str, set[str]]]:
    """skill_id 数组 -> [(展示名, 写法集合)]，按 id 去重并保持原顺序"""
    pairs: list[tuple[str, set[str]]] = []
    seen: set[int] = set()
    for skill_id in (ids or []):
        if skill_id in seen:
            continue
        seen.add(skill_id)
        skill = skill_map.get(skill_id)
        if skill is not None:
            pairs.append(_skill_info(skill))
    return pairs

def _classify(
    pairs: list[tuple[str, set[str]]], candidate_keys: set[str]
) -> tuple[list[str], list[str]]:
    matched: list[str] = []
    missing: list[str] = []
    for label, keys in pairs:
        if keys & candidate_keys:
            matched.append(label)
        else:
            missing.append(label)
    return matched, missing

def extract_features(
    job: Job,
    candidate: Candidate,
    skill_map: dict[int, Skill],
) -> MatchFeatures:
    feats = MatchFeatures()

    # ---- 技能 ----
    must_ids = list(dict.fromkeys(job.must_have_skills or []))
    must_set = set(must_ids)
    nice_ids = [sid for sid in dict.fromkeys(job.skills or []) if sid not in must_set]

    must_pairs = _skill_pairs(must_ids, skill_map)
    nice_pairs = _skill_pairs(nice_ids, skill_map)

    feats.must_skill_names = [label for label, _ in must_pairs]
    feats.nice_skill_names = [label for label, _ in nice_pairs]
    feats.candidate_skills = list(candidate.skills or [])

    candidate_keys = {_norm(s) for s in feats.candidate_skills if s}
    feats.matched_must, feats.missing_must = _classify(must_pairs, candidate_keys)
    feats.matched_nice, feats.missing_nice = _classify(nice_pairs, candidate_keys)

    # ---- 经验 ----
    feats.jd_min_years = _to_float(job.min_years)
    feats.candidate_years = _to_float(candidate.years_experience)
    if feats.jd_min_years is not None and feats.candidate_years is not None:
        feats.years_gap = round(feats.candidate_years - feats.jd_min_years, 1)

    # ---- 学历 ----
    feats.jd_edu_level = job.education_level
    feats.candidate_edu_level = candidate.education_level

    # ---- 地点 ----
    feats.jd_location = job.location
    feats.candidate_city = candidate.city
    if feats.jd_location:
        jd_city = feats.jd_location.split("/")[0].split("-")[0].strip()
        if jd_city.casefold() in _REMOTE_LOCATIONS:
            feats.location_match = True
        elif feats.candidate_city:
            cand_city = feats.candidate_city.strip()
            feats.location_match = (
                jd_city[:2] in cand_city or cand_city[:2] in jd_city
            )

    feats.jd_salary_min = job.salary_min
    feats.jd_salary_max = job.salary_max

    feats.candidate_name = candidate.name
    feats.job_title = job.title
    feats.candidate_current_title = candidate.current_title
    return feats