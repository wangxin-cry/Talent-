"""
JD 生成服务

优先调用真实 LLM（OpenAI 兼容接口）；未配置或调用失败时回退本地模板，
并通过 degraded / note 明确告知前端，绝不冒充 AI 生成。
"""
from __future__ import annotations

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.job import JDGenerateIn, JDGenerateOut, SkillBrief
from app.services.llm import ChatResult, LLMError, chat_json, is_configured, loads_json
from app.services.skills import resolve_skill_names

FALLBACK_KEYWORDS = ["沟通协作", "需求分析"]

SYSTEM_PROMPT = """你是资深招聘专家，为职位撰写中文 JD。
只输出一个 JSON 对象，不要 Markdown、不要解释，结构固定：
{
  "summary": "一句话职位简介",
  "description": "职责列表文本，每行以 1. 2. 3. 开头，共 4-6 条",
  "requirements": "任职要求列表文本，每行以 1. 2. 3. 开头，共 4-6 条",
  "skills": ["技能标准名，4-10 个"],
  "must_have_skills": ["必备技能，1-3 个，必须包含在 skills 中"]
}
要求：内容具体可发布，不编造公司信息，不包含薪资。"""

def _bullet(lines: list[str]) -> str:
    return "\n".join(f"{index}. {line}" for index, line in enumerate(lines, start=1))

def _clean_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]

def _template(data: JDGenerateIn, names: list[str]) -> dict[str, str]:
    scope = f"{data.department}的" if data.department else ""
    level = data.level or "本科及以上"
    skill_text = "、".join(names[:4]) if names else "相关技术栈"
    extra = "、".join(names[4:8]) if len(names) > 4 else "工程化实践"

    return {
        "summary": (
            f"我们正在寻找一位{level}的{data.title}，负责{scope}{data.title}方向的需求分析、"
            f"方案设计与落地，核心技能包括{skill_text}。"
        ),
        "description": _bullet(
            [
                f"负责{scope}{data.title}相关业务的需求分析、方案设计与开发落地；",
                "与产品、设计、测试协作，推动需求按时高质量交付；",
                f"参与 {skill_text} 相关模块的设计与优化，持续提升稳定性与性能；",
                "编写技术文档与单元测试，参与代码评审与技术分享；",
                "跟踪线上问题与用户反馈，持续迭代改进。",
            ]
        ),
        "requirements": _bullet(
            [
                f"{level}学历，具备扎实的{data.title}相关专业基础；",
                f"熟练掌握 {skill_text}，有实际项目落地经验；",
                f"熟悉 {extra}，具备良好的工程化意识；",
                "具备良好的沟通协作与问题解决能力，能独立负责模块；",
                "有招聘、HR SaaS 或企业服务经验者优先。",
            ]
        ),
    }

async def _generate_by_llm(
    data: JDGenerateIn, keywords: list[str]
) -> tuple[dict[str, str | list[str]], ChatResult]:
    user_prompt = (
        f"职位名称：{data.title}\n"
        f"部门：{data.department or '未指定'}\n"
        f"工作地点：{data.location or '未指定'}\n"
        f"级别：{data.level or '不限'}\n"
        f"关键词：{'、'.join(keywords)}"
    )
    result = await chat_json(SYSTEM_PROMPT, user_prompt)
    payload = loads_json(result.text)

    description = payload.get("description")
    requirements = payload.get("requirements")
    if not isinstance(description, str) or not description.strip():
        raise LLMError("模型返回的 description 为空")
    if not isinstance(requirements, str) or not requirements.strip():
        raise LLMError("模型返回的 requirements 为空")

    skills = _clean_list(payload.get("skills"))
    if not skills:
        raise LLMError("模型返回的 skills 为空")

    summary = payload.get("summary")
    return (
        {
            "summary": summary.strip()
            if isinstance(summary, str) and summary.strip()
            else f"{data.title} 职位说明",
            "description": description.strip(),
            "requirements": requirements.strip(),
            "skills": skills,
            "must_have_skills": _clean_list(payload.get("must_have_skills")),
        },
        result,
    )

async def generate_jd(db: AsyncSession, data: JDGenerateIn) -> JDGenerateOut:
    keywords = [item for item in data.keywords if item.strip()] or FALLBACK_KEYWORDS
    fallback_reason = ""

    if is_configured():
        try:
            payload, result = await _generate_by_llm(data, keywords)
            skills = await resolve_skill_names(db, payload["skills"])
            must_names = {name.casefold() for name in payload["must_have_skills"]}
            must = [skill for skill in skills if skill.name.casefold() in must_names] or skills[:2]

            return JDGenerateOut(
                summary=str(payload["summary"]),
                description=str(payload["description"]),
                requirements=str(payload["requirements"]),
                skills=[SkillBrief.model_validate(skill) for skill in skills],
                must_have_skills=[SkillBrief.model_validate(skill) for skill in must],
                ai_generated=True,
                degraded=False,
                model=result.model,
                note=None,
            )
        except LLMError as exc:
            logger.warning("AI 生成 JD 失败，回退模板：{}", exc)
            fallback_reason = str(exc)
    else:
        fallback_reason = "LLM 未配置（LLM_MOCK=true 或缺少 Base URL / API Key / 模型名）"

    skills = await resolve_skill_names(db, keywords)
    template = _template(data, [skill.name for skill in skills])

    return JDGenerateOut(
        summary=template["summary"],
        description=template["description"],
        requirements=template["requirements"],
        skills=[SkillBrief.model_validate(skill) for skill in skills],
        must_have_skills=[SkillBrief.model_validate(skill) for skill in skills[:2]],
        ai_generated=False,
        degraded=True,
        model=None,
        note=f"{fallback_reason}；已回退本地模板，可直接编辑后保存。",
    )