"""
规则打分引擎（docs §8 公式）

skill_score = 0.7 * must_have_coverage + 0.3 * nice_to_have_coverage
              （must_have_coverage < 1 时整体 × 0.6 惩罚）
exp_score   = 年限达标(0~0.6) + 相关领域加分(0~0.3) + 稳定性加分(0~0.1)
edu_score   = 学历满足 1.0 / 超配 0.9 / 不满足 0.5
other       = 地点匹配 0.5 + 薪资区间重叠 0.3 + 行业相关 0.2
final       = 100 * (0.50*skill + 0.30*exp + 0.12*edu + 0.08*other)

LLM 不参与打分——分数必须可复现。
"""
from __future__ import annotations

import re

from app.core.scoring_config import scoring
from app.services.match_features import MatchFeatures

# 职位名分词：英文/数字词 + 中文二元切分，用于判断「相关领域」
_LATIN_WORD = re.compile(r"[a-z0-9+#.]{2,}")
_CJK_SEGMENT = re.compile(r"[\u4e00-\u9fff]{2,}")

def _coverage(matched: list[str], total: list[str]) -> float:
    if not total:
        return 1.0
    return len(matched) / len(total)

def skill_score(feats: MatchFeatures) -> float:
    must_cov = _coverage(feats.matched_must, feats.must_skill_names)
    nice_cov = _coverage(feats.matched_nice, feats.nice_skill_names)
    raw = scoring.SKILL_MUST_WEIGHT * must_cov + scoring.SKILL_NICE_WEIGHT * nice_cov
    if must_cov < 1.0:
        raw *= scoring.SKILL_MISS_PENALTY
    return round(min(raw, 1.0), 4)

def _title_tokens(text: str | None) -> set[str]:
    """职位名词元：英文词 + 中文二元组，避免误用单字比较"""
    raw = (text or "").casefold()
    tokens = set(_LATIN_WORD.findall(raw))
    for segment in _CJK_SEGMENT.findall(raw):
        tokens.update(segment[i : i + 2] for i in range(len(segment) - 1))
    return tokens

def exp_score(feats: MatchFeatures) -> float:
    """经验分：年限达标 0~0.6 + 相关领域 0~0.3 + 稳定性 0~0.1"""
    if feats.jd_min_years is None:
        years_part = scoring.EXP_YEARS_CAP
    elif feats.candidate_years is None:
        years_part = 0.0
    elif feats.years_gap is not None and feats.years_gap >= 0:
        # 达到或超过最低年限即拿满年限分
        years_part = scoring.EXP_YEARS_CAP
    else:
        # 缺年限按缺口占最低要求的比例线性扣分
        denominator = max(feats.jd_min_years, 1.0)
        ratio = max(0.0, 1.0 + (feats.years_gap or 0.0) / denominator)
        years_part = scoring.EXP_YEARS_CAP * ratio

    # 相关领域：当前职位名与 JD 标题的词元重合度（0.5 重合即满分）
    relevance = 0.0
    jd_tokens = _title_tokens(feats.job_title)
    cand_tokens = _title_tokens(feats.candidate_current_title)
    common = jd_tokens & cand_tokens
    if common:
        relevance = scoring.EXP_RELEVANCE_CAP * min(1.0, len(common) / 2.0)

    # 稳定性：简历缺少任职时长明细，这里以「有工作年限」作代理指标
    stability = (
        scoring.EXP_STABILITY_CAP if (feats.candidate_years or 0) > 0 else 0.0
    )

    return round(min(years_part + relevance + stability, 1.0), 4)

def edu_score(feats: MatchFeatures) -> float:
    """学历分：满足 1.0 / 超配 0.9 / 不满足 0.5"""
    if not feats.jd_edu_level:
        return 1.0
    jd_rank = scoring.EDU_RANK.get(feats.jd_edu_level, 0)
    cand_rank = scoring.EDU_RANK.get(feats.candidate_edu_level or "", 0)
    if cand_rank == 0:
        return scoring.EDU_BELOW
    if cand_rank >= jd_rank:
        return scoring.EDU_MEET if cand_rank == jd_rank else scoring.EDU_OVER
    return scoring.EDU_BELOW

def other_score(feats: MatchFeatures) -> float:
    """其他分：地点 0.5 + 薪资 0.3 + 行业 0.2"""
    location = scoring.OTHER_LOCATION_W if feats.location_match else 0.0
    # 简历没有期望薪资字段：JD 未写薪资视为不限制给满分，写了也只给中性分
    if feats.jd_salary_min is None or feats.jd_salary_max is None:
        salary = scoring.OTHER_SALARY_W
    else:
        salary = scoring.OTHER_SALARY_W * 0.7
    # 行业字段暂未入库，统一给中性分，避免虚构匹配
    industry = scoring.OTHER_INDUSTRY_W * 0.7
    return round(min(location + salary + industry, 1.0), 4)

def compute_scores(feats: MatchFeatures) -> dict:
    """计算四个维度分 + 综合分，返回可直接落库的 dict"""
    s_skill = skill_score(feats)
    s_exp = exp_score(feats)
    s_edu = edu_score(feats)
    s_other = other_score(feats)

    final = 100 * (
        scoring.W_SKILL * s_skill
        + scoring.W_EXP * s_exp
        + scoring.W_EDU * s_edu
        + scoring.W_OTHER * s_other
    )
    final = round(min(max(final, 0.0), 100.0), 1)

    return {
        "score": final,
        "skill_score": round(s_skill, 4),
        "exp_score": round(s_exp, 4),
        "edu_score": round(s_edu, 4),
        "other_score": round(s_other, 4),
    }