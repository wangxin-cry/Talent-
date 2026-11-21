"""
匹配理由生成：模板为主，LLM 润色可选（失败自动降级模板）

输出五段：summary / matched_skills / missing_skills / risks / suggestion
"""
from __future__ import annotations

from app.core.scoring_config import scoring
from app.services.match_features import MatchFeatures


def _fmt_years(gap: float | None) -> str:
    if gap is None:
        return "经验年限信息不足"
    if gap >= 0:
        return f"经验超要求 {gap:.1f} 年"
    return f"经验差 {abs(gap):.1f} 年"


def build_template_explanation(feats: MatchFeatures, scores: dict) -> dict:
    """纯模板生成理由，零 LLM 成本，永远可用"""
    matched = feats.matched_must + feats.matched_nice
    missing = feats.missing_must + feats.missing_nice

    # summary：一句话结论
    score = scores["score"]
    if score >= 80:
        verdict = "高度匹配"
    elif score >= 60:
        verdict = "基本匹配"
    elif score >= 40:
        verdict = "部分匹配"
    else:
        verdict = "匹配度较低"

    parts = [f"{verdict}（{score:.0f} 分）", f"命中 {len(matched)} 项"]
    if missing:
        parts.append(f"缺 {len(missing)} 项")
    if feats.years_gap is not None:
        parts.append(_fmt_years(feats.years_gap))
    summary = "，".join(parts)

    # risks：扣分点
    risks: list[str] = []
    if feats.missing_must:
        risks.append(f"必备技能未掌握：{'、'.join(feats.missing_must)}")
    if feats.years_gap is not None and feats.years_gap < 0:
        risks.append(f"工作经验低于要求 {abs(feats.years_gap):.1f} 年")
    if scores["edu_score"] < scoring.EDU_MEET and feats.jd_edu_level:
        risks.append("学历未达到职位最低要求")
    if not feats.location_match and feats.jd_location:
        risks.append(f"工作地点不匹配（JD: {feats.jd_location}）")

    # suggestion
    if score >= 80:
        suggestion = "建议优先安排面试，重点确认缺失技能的可替代性。"
    elif score >= 60:
        suggestion = "可进入面试流程，面试中重点考察缺失技能与经验差距。"
    elif feats.missing_must:
        suggestion = "必备技能缺口较大，建议先确认是否有可迁移经验再决定。"
    else:
        suggestion = "匹配度偏低，建议暂缓或转推荐其他更合适的职位。"

    return {
        "summary": summary,
        "matched_skills": matched,
        "missing_skills": missing,
        "risks": risks,
        "suggestion": suggestion,
    }


async def build_explanation(feats: MatchFeatures, scores: dict, use_llm: bool = False) -> dict:
    """
    生成匹配理由。
    use_llm=True 时尝试用 LLM 润色 summary/suggestion，失败自动降级模板。
    """
    template = build_template_explanation(feats, scores)
    if not use_llm:
        return template

    try:
        from app.services import llm

        prompt = (
            f"职位：{feats.job_title}\n"
            f"候选人：{feats.candidate_name or '未知'}\n"
            f"综合分：{scores['score']:.0f}/100（技能 {scores['skill_score']:.2f}、"
            f"经验 {scores['exp_score']:.2f}、学历 {scores['edu_score']:.2f}、其他 {scores['other_score']:.2f}）\n"
            f"命中技能：{', '.join(template['matched_skills']) or '无'}\n"
            f"缺失技能：{', '.join(template['missing_skills']) or '无'}\n"
            f"风险：{'；'.join(template['risks']) or '无'}\n"
            "请用一句话给出匹配结论，并给出一句面试建议。输出 JSON："
            '{"summary": "...", "suggestion": "..."}'
        )
        result = await llm.chat_json("你是招聘匹配顾问", prompt, temperature=0.3)
        polished = llm.loads_json(result.text)
        if isinstance(polished, dict):
            if polished.get("summary"):
                template["summary"] = str(polished["summary"])[:200]
            if polished.get("suggestion"):
                template["suggestion"] = str(polished["suggestion"])[:200]
    except Exception:  # noqa: BLE001
        pass  # LLM 失败静默降级为模板
    return template
