"""
AI 面试题生成（阶段六）

输入：职位要求（必备/加分技能、任职要求）+ 候选人简历（项目、任职、技能）+ 匹配缺口
输出：6~8 道题，每题带考察点、引用依据、追问

硬约束：
- 至少 5 题引用具体项目 / 技能 / 工作经历 / 岗位缺口，禁止"请自我介绍"类通用题
- LLM 不可用或不达标时，用模板题兜底（确定性、可测试）
- job + resume + 缺口 指纹缓存，重复点击直接读库
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import sha256_hex
from app.models.application import Application
from app.models.candidate import Candidate, Resume
from app.models.interview_question import InterviewQuestion
from app.models.job import Job
from app.models.match_result import MatchResult
from app.schemas.application import QuestionOut, QuestionSetOut
from app.services import llm
from app.services import rag
from app.services.match_features import extract_features
from app.services.skills import load_skill_map

QUESTION_VERSION = "iq-v2"
MIN_QUESTIONS = 6
MAX_QUESTIONS = 8
MIN_EVIDENCE = 5

# 可视为「引用具体经历」的依据前缀
EVIDENCE_MARKERS = ("项目：", "技能：", "经历：", "任职：", "缺口：")


@dataclass
class QuestionDraft:
    category: str
    question: str
    looking_for: str
    reference: str
    follow_up: str = ""


@dataclass
class PrepContext:
    """生成面试题所需的全部事实"""

    job_title: str = ""
    requirements: str = ""
    description: str = ""
    must_skills: list[str] = field(default_factory=list)
    nice_skills: list[str] = field(default_factory=list)

    candidate_name: str = ""
    current_title: str = ""
    current_company: str = ""
    years: float | None = None
    skills: list[str] = field(default_factory=list)
    projects: list[dict] = field(default_factory=list)
    work: list[dict] = field(default_factory=list)

    matched_must: list[str] = field(default_factory=list)
    missing_must: list[str] = field(default_factory=list)
    matched_nice: list[str] = field(default_factory=list)
    missing_nice: list[str] = field(default_factory=list)
    years_gap: float | None = None
    jd_min_years: float | None = None


def _snippet(text: str | None, limit: int = 80) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + "…"


def _normalize_projects(structured: dict | None) -> list[dict]:
    projects: list[dict] = []
    for item in (structured or {}).get("projects") or []:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("project_name") or item.get("title")
        tech = item.get("stack") or item.get("tech") or item.get("technologies") or []
        if isinstance(tech, str):
            tech = [tech]
        description = item.get("description") or item.get("detail") or item.get("summary")
        if not (name or description):
            continue
        projects.append(
            {
                "name": str(name) if name else "",
                "role": item.get("role") or "",
                "tech": [str(value) for value in tech][:6],
                "description": description or "",
            }
        )
    return projects[:4]


def _normalize_work(structured: dict | None) -> list[dict]:
    work: list[dict] = []
    for item in (structured or {}).get("work") or []:
        if not isinstance(item, dict):
            continue
        company = item.get("company")
        title = item.get("title") or item.get("position")
        if not (company or title):
            continue
        work.append(
            {
                "company": str(company) if company else "",
                "title": str(title) if title else "",
                "description": item.get("description") or "",
            }
        )
    return work[:4]


async def _primary_resume(db: AsyncSession, candidate_id: int) -> Resume | None:
    return (
        await db.execute(
            select(Resume)
            .where(Resume.candidate_id == candidate_id, Resume.is_primary.is_(True))
            .order_by(Resume.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _load_context(
    db: AsyncSession, application: Application
) -> tuple[PrepContext, Resume | None]:
    job = await db.get(Job, application.job_id)
    candidate = await db.get(Candidate, application.candidate_id)
    resume = await _primary_resume(db, application.candidate_id)

    ctx = PrepContext()
    if job is not None:
        skill_map = await load_skill_map(
            db, list(set([*(job.must_have_skills or []), *(job.skills or [])]))
        )
        must_ids = list(dict.fromkeys(job.must_have_skills or []))
        must_set = set(must_ids)
        nice_ids = [sid for sid in dict.fromkeys(job.skills or []) if sid not in must_set]

        def _names(ids: list[int]) -> list[str]:
            names: list[str] = []
            for skill_id in ids:
                skill = skill_map.get(skill_id)
                if skill is not None:
                    names.append(skill.display_name or skill.name)
            return names

        ctx.job_title = job.title
        ctx.requirements = job.requirements or ""
        ctx.description = job.description or ""
        ctx.must_skills = _names(must_ids)
        ctx.nice_skills = _names(nice_ids)
        ctx.jd_min_years = float(job.min_years) if job.min_years is not None else None

        if candidate is not None:
            feats = extract_features(job, candidate, skill_map)
            ctx.matched_must = feats.matched_must
            ctx.missing_must = feats.missing_must
            ctx.matched_nice = feats.matched_nice
            ctx.missing_nice = feats.missing_nice
            ctx.years_gap = feats.years_gap

    if candidate is not None:
        ctx.candidate_name = candidate.name or ""
        ctx.current_title = candidate.current_title or ""
        ctx.current_company = candidate.current_company or ""
        ctx.skills = list(candidate.skills or [])
        ctx.years = (
            float(candidate.years_experience)
            if candidate.years_experience is not None
            else None
        )

    if resume is not None:
        ctx.projects = _normalize_projects(resume.structured)
        ctx.work = _normalize_work(resume.structured)

    # 已有匹配结果时优先用落库的缺口（与排名页展示一致）
    match = (
        await db.execute(
            select(MatchResult)
            .where(
                MatchResult.job_id == application.job_id,
                MatchResult.candidate_id == application.candidate_id,
            )
            .order_by(MatchResult.create_time.desc(), MatchResult.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if match is not None:
        features = (match.detail or {}).get("features") or {}
        if features:
            ctx.matched_must = features.get("matched_must") or ctx.matched_must
            ctx.missing_must = features.get("missing_must") or ctx.missing_must
            ctx.matched_nice = features.get("matched_nice") or ctx.matched_nice
            ctx.missing_nice = features.get("missing_nice") or ctx.missing_nice
            ctx.years_gap = features.get("years_gap", ctx.years_gap)
            ctx.jd_min_years = features.get("jd_min_years", ctx.jd_min_years)

    return ctx, resume


def _project_label(project: dict) -> str:
    return project.get("name") or "近期项目"


def _project_tech(project: dict) -> str:
    tech = project.get("tech") or []
    return "、".join(tech[:3]) if tech else "相关技术栈"


def build_template_questions(ctx: PrepContext) -> list[QuestionDraft]:
    """确定性模板题：至少 5 题引用项目/技能/经历/缺口"""
    drafts: list[QuestionDraft] = []
    p0 = ctx.projects[0] if ctx.projects else None
    p1 = ctx.projects[1] if len(ctx.projects) > 1 else None

    # 1. 项目深挖
    if p0:
        name, tech = _project_label(p0), _project_tech(p0)
        drafts.append(
            QuestionDraft(
                category="project",
                question=(
                    f"请介绍「{name}」的整体架构和你负责的部分：为什么选择 {tech}？"
                    "当时做过哪些关键取舍？"
                ),
                looking_for="项目真实性、架构理解与技术决策能力",
                reference=f"项目：{name}（{tech}）",
                follow_up=f"如果「{name}」的流量增长 10 倍，最先出现瓶颈的环节是哪里？",
            )
        )
    elif ctx.current_company or ctx.current_title:
        drafts.append(
            QuestionDraft(
                category="project",
                question=(
                    f"你在{ctx.current_company or '最近一家公司'}担任{ctx.current_title or '当前职位'}，"
                    "请挑一个你主导的项目，说明目标、方案和最终结果。"
                ),
                looking_for="项目主导能力与结果意识",
                reference=f"任职：{ctx.current_company or '最近公司'} · {ctx.current_title or '当前职位'}",
                follow_up="这个项目里最难的决策是什么？如果重做你会怎么改？",
            )
        )
    else:
        drafts.append(
            QuestionDraft(
                category="project",
                question=f"请结合你过去最具代表性的项目，说明它和「{ctx.job_title}」的匹配点。",
                looking_for="经验相关性",
                reference="经历：简历项目信息有限，请候选人补充",
                follow_up="该项目中你独立负责的部分占多少？",
            )
        )

    # 2. 第二个项目 / 难点排查
    if p1:
        name, tech = _project_label(p1), _project_tech(p1)
        drafts.append(
            QuestionDraft(
                category="project",
                question=(
                    f"「{name}」中你用到了 {tech}，请讲一次最棘手的问题排查过程："
                    "现象、定位路径、根因和修复方案。"
                ),
                looking_for="排障方法论与工程严谨度",
                reference=f"项目：{name}（{tech}）",
                follow_up="如何验证修复有效？有没有补充监控或回归用例？",
            )
        )
    elif p0:
        name = _project_label(p0)
        drafts.append(
            QuestionDraft(
                category="project",
                question=(
                    f"在「{name}」中，你做过哪个后来被证明是错误的技术决策？"
                    "你是如何发现并纠正它的？"
                ),
                looking_for="反思能力与技术判断",
                reference=f"项目：{name}",
                follow_up="这次经历之后，你在方案评审上增加了哪些检查项？",
            )
        )
    else:
        drafts.append(
            QuestionDraft(
                category="experience",
                question="请讲一次线上故障的处理经历，说明你在其中的角色和复盘结论。",
                looking_for="线上问题处理能力",
                reference="经历：简历未提供项目细节，请候选人补充",
                follow_up="复盘后落地了哪些改进？",
            )
        )

    # 3. 命中的必备技能
    skill = (ctx.matched_must or ctx.must_skills or ctx.skills or [""])[0]
    if skill:
        project_ref = f"项目：{_project_label(p0)}" if p0 else "技能：简历技能列表"
        drafts.append(
            QuestionDraft(
                category="skill",
                question=(
                    f"岗位必备的 {skill} 已出现在你的经历中，请结合"
                    f"{('「' + _project_label(p0) + '」') if p0 else '实际工作'}说明："
                    "你在生产环境如何落地、如何做性能与稳定性保障？"
                ),
                looking_for=f"{skill} 的实战深度",
                reference=f"技能：{skill} / {project_ref}",
                follow_up=f"如果让你给团队做一次 {skill} 的分享，你会讲哪三个要点？",
            )
        )

    # 4. 缺失的必备技能
    if ctx.missing_must:
        missing = ctx.missing_must[0]
        drafts.append(
            QuestionDraft(
                category="gap",
                question=(
                    f"岗位要求 {missing}，但简历中没有直接体现。"
                    "请说明你对它的实际了解程度，以及入职后两周内的上手计划。"
                ),
                looking_for="缺口补齐意愿与学习路径",
                reference=f"缺口：岗位必备 {missing} 未在简历中体现",
                follow_up=f"你过去有没有在短时间内自学一门新技术的例子？结果如何？",
            )
        )
    else:
        skill = (ctx.must_skills or ctx.skills or [""])[0]
        if skill:
            drafts.append(
                QuestionDraft(
                    category="skill",
                    question=f"岗位必备技能你已覆盖。请说明你对 {skill} 的边界理解：哪些场景不该用它？",
                    looking_for="技术边界与选型判断",
                    reference=f"技能：{skill}（岗位必备）",
                    follow_up="能举一个反例说明误用它的代价吗？",
                )
            )

    # 5. 第二个缺口 / 加分项
    pool = ctx.missing_must[1:] + ctx.missing_nice
    if pool:
        gap_skill = pool[0]
        drafts.append(
            QuestionDraft(
                category="gap",
                question=(
                    f"岗位还关注 {gap_skill}，简历中体现较少。"
                    "请结合你做过的系统，说明你对它的理解以及可以迁移的经验。"
                ),
                looking_for="知识迁移能力",
                reference=f"缺口：{gap_skill} 在简历中体现不足",
                follow_up="如果一周内要产出方案，你会先补齐哪部分知识？",
            )
        )
    elif ctx.nice_skills:
        nice = ctx.nice_skills[0]
        drafts.append(
            QuestionDraft(
                category="skill",
                question=f"加分项 {nice} 与岗位相关，你在实际项目中用过它解决什么问题？",
                looking_for="加分技能的实战价值",
                reference=f"技能：{nice}（岗位加分项）",
                follow_up="没有它的话，你会用什么替代方案？",
            )
        )

    # 6. 经验年限
    if ctx.jd_min_years is not None and ctx.years is not None:
        if (ctx.years_gap or 0) < 0:
            drafts.append(
                QuestionDraft(
                    category="experience",
                    question=(
                        f"岗位要求 {ctx.jd_min_years:g} 年经验，你目前 {ctx.years:g} 年。"
                        "请举一个能证明你具备同等复杂度的项目，并说明你独立做出的关键决策。"
                    ),
                    looking_for="经验成色与独立担当",
                    reference=(
                        f"经历：{ctx.years:g} 年 / 岗位要求 {ctx.jd_min_years:g} 年"
                        f"（差 {abs(ctx.years_gap or 0):g} 年）"
                    ),
                    follow_up="这个项目里如果没有你，最可能出问题的是哪一环？",
                )
            )
        else:
            drafts.append(
                QuestionDraft(
                    category="experience",
                    question=(
                        f"你有 {ctx.years:g} 年经验，已满足岗位 {ctx.jd_min_years:g} 年的要求。"
                        "请挑一个最能体现你技术判断力的决策，说明当时的权衡。"
                    ),
                    looking_for="经验深度与判断力",
                    reference=f"经历：{ctx.years:g} 年 / 岗位要求 {ctx.jd_min_years:g} 年",
                    follow_up="如果当时选另一条路，结果会有什么不同？",
                )
            )
    elif ctx.years is not None:
        drafts.append(
            QuestionDraft(
                category="experience",
                question=(
                    f"你有 {ctx.years:g} 年工作经验，请说明其中哪一段成长最快，"
                    "以及你从中学到了什么可复用的方法。"
                ),
                looking_for="成长曲线与复盘能力",
                reference=f"经历：{ctx.years:g} 年工作经验",
                follow_up="这段经历如何影响你现在带项目的方式？",
            )
        )

    # 7. 岗位职责场景
    requirement = _snippet(ctx.requirements or ctx.description, 90)
    if requirement:
        drafts.append(
            QuestionDraft(
                category="scenario",
                question=(
                    f"岗位要求中提到「{requirement}」。"
                    "如果让你入职 30 天内推进这件事，你会如何拆解目标、识别风险？"
                ),
                looking_for="岗位理解与落地规划",
                reference=f"岗位要求：{requirement}",
                follow_up="前两周你会先找哪些人沟通、确认哪些信息？",
            )
        )
    else:
        drafts.append(
            QuestionDraft(
                category="scenario",
                question=f"如果入职「{ctx.job_title}」，你前 30 天会优先解决哪三个问题？为什么？",
                looking_for="优先级判断",
                reference=f"岗位：{ctx.job_title}",
                follow_up="如何衡量这三个问题是否被解决？",
            )
        )

    # 8. 动机与匹配
    if p0:
        drafts.append(
            QuestionDraft(
                category="motivation",
                question=(
                    f"你目前在{ctx.current_company or '现公司'}担任{ctx.current_title or '现职位'}，"
                    f"为什么考虑「{ctx.job_title}」？请结合「{_project_label(p0)}」说明你的匹配点。"
                ),
                looking_for="求职动机与岗位匹配度",
                reference=(
                    f"任职：{ctx.current_company or '现公司'} · {ctx.current_title or '现职位'}"
                    f"；项目：{_project_label(p0)}"
                ),
                follow_up="未来两年你希望在这个岗位上成长为什么角色？",
            )
        )
    else:
        drafts.append(
            QuestionDraft(
                category="motivation",
                question=f"为什么选择「{ctx.job_title}」？你认为自己最需要补齐的一点是什么？",
                looking_for="自我认知与动机",
                reference=f"岗位：{ctx.job_title}；技能：{'、'.join(ctx.skills[:3]) or '简历技能'}",
                follow_up="你希望团队给你提供什么支持？",
            )
        )

    return drafts[:MAX_QUESTIONS]


def _evidence_count(drafts: list[QuestionDraft]) -> int:
    return sum(
        1
        for draft in drafts
        if any(marker in (draft.reference or "") for marker in EVIDENCE_MARKERS)
    )


SYSTEM_PROMPT = """你是资深技术面试官。请根据职位要求与候选人简历生成 6~8 道个性化面试题。
硬性要求：
1. 每题必须引用简历中的具体项目、公司、技能，或明确的岗位缺口，禁止"请自我介绍"类通用题；
2. 至少 5 题的 reference 字段以「项目：」「技能：」「经历：」「任职：」「缺口：」之一开头；
3. 若提供了「参考材料」，只把它当作出题灵感，禁止照抄原文，禁止编造材料中没有的事实；
4. 只输出 JSON，不要任何解释，格式：
{"questions":[{"category":"project|skill|gap|experience|scenario|motivation","question":"题目","looking_for":"考察点","reference":"引用依据","follow_up":"追问"}]}
"""


def _build_user_prompt(ctx: PrepContext, references: list[dict] | None = None) -> str:
    facts = {
        "职位": ctx.job_title,
        "必备技能": ctx.must_skills,
        "加分技能": ctx.nice_skills,
        "任职要求": _snippet(ctx.requirements, 600),
        "候选人": {
            "姓名": ctx.candidate_name,
            "当前职位": ctx.current_title,
            "当前公司": ctx.current_company,
            "工作年限": ctx.years,
            "技能": ctx.skills[:20],
            "项目": ctx.projects,
            "工作经历": ctx.work,
        },
        "匹配缺口": {
            "已命中必备": ctx.matched_must,
            "缺失必备": ctx.missing_must,
            "已命中加分": ctx.matched_nice,
            "缺失加分": ctx.missing_nice,
            "年限要求": ctx.jd_min_years,
            "年限差": ctx.years_gap,
        },
    }
    if references:
        facts["参考材料（仅作灵感，禁止照抄）"] = [
            {
                "类型": item.get("type"),
                "标题": item.get("title"),
                "片段": _snippet(item.get("snippet"), 260),
            }
            for item in references[:8]
        ]
    return json.dumps(facts, ensure_ascii=False, default=str)


def _from_llm_payload(payload: dict) -> list[QuestionDraft] | None:
    raw = payload.get("questions")
    if not isinstance(raw, list):
        return None

    drafts: list[QuestionDraft] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        if not question:
            continue
        drafts.append(
            QuestionDraft(
                category=str(item.get("category") or "general")[:20],
                question=question,
                looking_for=str(item.get("looking_for") or "").strip(),
                reference=str(item.get("reference") or "").strip(),
                follow_up=str(item.get("follow_up") or "").strip(),
            )
        )

    if len(drafts) < MIN_QUESTIONS:
        return None
    drafts = drafts[:MAX_QUESTIONS]
    if _evidence_count(drafts) < MIN_EVIDENCE:
        return None
    return drafts


async def _generate_with_llm(
    ctx: PrepContext, application: Application, references: list[dict] | None = None
) -> list[QuestionDraft] | None:
    if not llm.is_configured():
        return None
    try:
        result = await llm.chat_json(
            SYSTEM_PROMPT,
            _build_user_prompt(ctx, references),
            temperature=0.5,
            feature="interview_generate",
            user_id=application.created_by,
            job_id=application.job_id,
            candidate_id=application.candidate_id,
            agent="InterviewAssistantAgent",
        )
        payload = llm.loads_json(result.text)
    except llm.LLMError:
        return None
    return _from_llm_payload(payload)


def fingerprint_of(
    job: Job, resume: Resume | None, ctx: PrepContext, *, rag_enabled: bool = False
) -> str:
    raw = "|".join(
        [
            QUESTION_VERSION,
            f"v{job.jd_version}",
            resume.content_hash or "" if resume else "",
            ",".join(ctx.missing_must),
            ",".join(ctx.matched_must),
            str(ctx.years_gap),
            str(ctx.jd_min_years),
            f"rag:{1 if rag_enabled else 0}",
        ]
    )
    return sha256_hex(raw)


def _to_set(
    application_id: int,
    rows: list[InterviewQuestion],
    *,
    cached: bool,
    rag_sources: list[dict] | None = None,
) -> QuestionSetOut:
    source = rows[0].source if rows else "none"
    # 从库里还原参考来源：命中缓存或刷新页面时也要能看到"参考了什么"
    if rag_sources is None and rows:
        rag_sources = list((rows[0].rag_sources or []))
    return QuestionSetOut(
        application_id=application_id,
        cached=cached,
        source=source,
        total=len(rows),
        rag_used=source == "llm_rag",
        rag_sources=rag_sources or [],
        questions=[QuestionOut.model_validate(row) for row in rows],
    )


async def list_questions(db: AsyncSession, application: Application) -> QuestionSetOut:
    """读取已生成的题目（不触发 LLM）"""
    rows = (
        await db.execute(
            select(InterviewQuestion)
            .where(InterviewQuestion.application_id == application.id)
            .order_by(InterviewQuestion.sort_order.asc(), InterviewQuestion.id.asc())
        )
    ).scalars().all()
    return _to_set(application.id, list(rows), cached=bool(rows))


async def generate_questions(
    db: AsyncSession,
    application: Application,
    *,
    use_llm: bool = False,
    use_rag: bool | None = None,
    force: bool = False,
) -> QuestionSetOut:
    """生成 6~8 道题；指纹命中时直接返回缓存"""
    ctx, resume = await _load_context(db, application)
    job = await db.get(Job, application.job_id)
    if job is None:
        return QuestionSetOut(application_id=application.id)

    effective_rag = (
        settings.RAG_ENABLED if use_rag is None else bool(use_rag and settings.RAG_ENABLED)
    )
    fingerprint = fingerprint_of(job, resume, ctx, rag_enabled=effective_rag)

    if not force:
        cached_rows = (
            await db.execute(
                select(InterviewQuestion)
                .where(
                    InterviewQuestion.application_id == application.id,
                    InterviewQuestion.fingerprint == fingerprint,
                )
                .order_by(InterviewQuestion.sort_order.asc(), InterviewQuestion.id.asc())
            )
        ).scalars().all()
        if cached_rows:
            return _to_set(application.id, list(cached_rows), cached=True)

    references: list[dict] = []
    if effective_rag and use_llm:
        candidate = await db.get(Candidate, application.candidate_id)
        references = await rag.retrieve_for_interview(db, application, job, candidate)

    source = "template"
    drafts: list[QuestionDraft] | None = None
    if use_llm:
        drafts = await _generate_with_llm(ctx, application, references)
        if drafts:
            source = "llm_rag" if references else "llm"
    if not drafts:
        drafts = build_template_questions(ctx)

    # 新旧版本题目一起清理，避免准备页出现重复题
    await db.execute(
        delete(InterviewQuestion).where(InterviewQuestion.application_id == application.id)
    )

    rows: list[InterviewQuestion] = []
    for index, draft in enumerate(drafts):
        row = InterviewQuestion(
            application_id=application.id,
            job_id=application.job_id,
            candidate_id=application.candidate_id,
            category=draft.category,
            question=draft.question,
            looking_for=draft.looking_for,
            reference=draft.reference,
            follow_up=draft.follow_up,
            sort_order=index,
            source=source,
            fingerprint=fingerprint,
            company_id=1,
            rag_sources=references if source == "llm_rag" else [],
        )
        db.add(row)
        rows.append(row)
    await db.commit()
    for row in rows:
        await db.refresh(row)
    return _to_set(
        application.id,
        rows,
        cached=False,
        rag_sources=references if source == "llm_rag" else [],
    )
