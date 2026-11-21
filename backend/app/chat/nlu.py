"""对话意图识别与槽位抽取（规则优先，LLM 兜底）

设计原则（对应设计文档 §6）：
- 高频意图走规则，快且零成本；
- 规则不命中才尝试 LLM；LLM 不可用/失败时返回 unknown，不阻塞页面按钮；
- 槽位先查会话上下文，再查话里明确提到的对象，最后才追问。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import Application
from app.models.candidate import Candidate
from app.models.chat import ChatSession
from app.models.job import STATUS_ARCHIVED, Job
from app.models.skill import Skill
from app.services import llm

# 意图 → 工具 / 危险等级
INTENT_META: dict[str, dict] = {
    "resume_upload": {"label": "解析简历", "level": "write", "tool": "parse_resume"},
    "search_candidates": {
        "label": "人才库检索",
        "level": "read",
        "tool": "search_candidates",
    },
    "match": {"label": "智能匹配", "level": "read", "tool": "match_job"},
    "interview": {
        "label": "生成面试题",
        "level": "read",
        "tool": "generate_interview",
    },
    "advance_status": {
        "label": "推进状态",
        "level": "irreversible",
        "tool": "advance_status",
    },
    "reject_candidate": {
        "label": "淘汰候选人",
        "level": "irreversible",
        "tool": "reject_candidate",
    },
    "publish_job": {"label": "发布职位", "level": "write", "tool": "publish_job"},
    "application_status": {
        "label": "查候选人进度",
        "level": "read",
        "tool": "get_application_status",
    },
    "analytics": {"label": "看板数据", "level": "read", "tool": "query_analytics"},
    "jd_generate": {"label": "生成 JD", "level": "read", "tool": "generate_jd"},
}

# 顺序即优先级：不可逆 / 明确动作优先，避免「把张伟推到面试」被识别成面试题
_RULES: list[tuple[str, str, float]] = [
    ("reject_candidate", r"淘汰|拒掉|拒绝掉|拉黑|不合适.*(?:淘汰|拒)|不通过", 0.95),
    (
        "publish_job",
        # 词序容忍：常见说法有「发布这个职位」「把职位上架」「职位发出去」
        r"发布.{0,6}职位|上架.{0,6}职位|职位.{0,6}(?:上架|发布|开放)|开放.{0,6}职位|"
        r"把.{0,20}职位.{0,6}(?:发布|上架)",
        0.92,
    ),
    (
        "advance_status",
        r"推到|推进到|推进一下|进入.{0,4}面试|安排.{0,4}面试|转.{0,4}面试|"
        r"发\s*offer|录用|入职|状态(?:改|变更|更新)|改为|变更为|移动到|流转到",
        0.92,
    ),
    (
        "application_status",
        r"什么状态|状态如何|现在.{0,6}(?:状态|进度|进展)|到哪一步|在哪一步|"
        r"进度如何|进展如何|流程走到|在第几轮",
        0.9,
    ),
    (
        "analytics",
        r"渠道|漏斗|转化率|招聘周期|看板|数据|统计|报表|成本|效率|"
        r"本月|这个月|上月|本周|这周|趋势",
        0.86,
    ),
    ("interview", r"面试题|出题|面试准备|面试问题|题目|考察点", 0.92),
    (
        "resume_upload",
        r"上传|传了|传一批|导入简历|解析.{0,6}简历|简历.{0,4}(?:解析|入库)|"
        r"批量.{0,6}简历",
        0.9,
    ),
    (
        "search_candidates",
        r"人才库|找找|找一下|搜索|搜一下|检索|查找|筛出|会.{0,8}的候选人|"
        r"候选人.{0,6}会|有哪些.{0,8}候选人",
        0.84,
    ),
    (
        "match",
        r"匹配|适合|合适|人岗|排名|谁最|挑出|看看.{0,8}谁|哪个人|候选人.{0,4}适合|"
        r"排个序|哪个更合适",
        0.86,
    ),
    ("jd_generate", r"(?:^|\W)JD(?:\W|$)|职位描述|岗位描述|招聘文案|职位介绍", 0.9),
]

_CN_NUM = {
    "一": 1,
    "两": 2,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


@dataclass
class Decision:
    """一次意图判断结果"""

    intent: str | None = None
    confidence: float = 0.0
    matched_by: str = "rule"
    slots: dict = field(default_factory=dict)
    missing: str | None = None
    clarify_question: str | None = None
    options: list[dict] = field(default_factory=list)


def classify_intent(text: str) -> tuple[str | None, float]:
    """纯规则分类（同步、可单元测试）"""
    cleaned = (text or "").strip()
    if not cleaned:
        return None, 0.0
    for intent, pattern, confidence in _RULES:
        if re.search(pattern, cleaned, re.IGNORECASE):
            return intent, confidence
    return None, 0.0


async def classify_with_llm(
    db: AsyncSession,
    text: str,
    history: list[dict],
    *,
    user_id: int | None = None,
) -> tuple[str | None, float, dict]:
    """规则不命中时尝试 LLM；任何异常都降级为 unknown"""
    if not llm.is_configured():
        return None, 0.0, {}

    from app.chat.tools import tool_prompt

    system = (
        "你是招聘系统的意图识别器。根据用户这句话和最近对话，判断意图并抽取槽位。"
        "只输出 JSON：{\"intent\": \"...\", \"slots\": {...}, \"confidence\": 0.0}。"
        f"可用意图：{', '.join(INTENT_META)}；无法判断时 intent 为 null。"
        f"可用工具与参数：{tool_prompt()}"
    )
    recent = "\n".join(
        f"{item.get('role')}: {item.get('content')}" for item in history[-10:]
    )
    prompt = f"最近对话：\n{recent}\n\n用户最新一句：{text}"
    try:
        result = await llm.chat_json(
            system,
            prompt,
            temperature=0.1,
            feature="chat_intent",
            user_id=user_id,
            agent="Manager",
        )
        import json

        payload = json.loads(_strip_json(result.text))
        intent = payload.get("intent")
        if intent not in INTENT_META:
            return None, 0.0, {}
        return intent, float(payload.get("confidence") or 0.6), payload.get("slots") or {}
    except Exception as exc:  # noqa: BLE001
        logger.info(f"对话意图 LLM 兜底失败，按规则结果处理：{exc}")
        return None, 0.0, {}


def _strip_json(text: str) -> str:
    """模型有时会包 ```json ... ```，这里去掉围栏"""
    value = text.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[-1]
        if value.endswith("```"):
            value = value[:-3]
    start = value.find("{")
    end = value.rfind("}")
    return value[start : end + 1] if start >= 0 and end > start else value


# ---------------------------------------------------------------- 槽位
def _match_job_in_text(jobs: list[Job], text: str) -> Job | None:
    """按标题 / 标题核心词匹配职位，优先已发布"""
    lowered = text.lower().replace(" ", "")
    best: tuple[int, Job] | None = None
    for job in jobs:
        if not job.title:
            continue
        title = job.title.replace(" ", "")
        candidates: list[str] = [title]
        core = re.sub(
            r"(高级|资深|初级|中级)?(工程师|开发工程师|开发|专员|经理|设计师|架构师|主管)$",
            "",
            title,
        )
        if len(core) >= 2:
            candidates.append(core)
        for token in re.split(r"[/·|\-_\s]", core):
            if len(token) >= 2 and re.search(r"[\u4e00-\u9fa5]", token):
                candidates.append(token)

        score = 0
        for candidate in candidates:
            if candidate and candidate.lower() in lowered:
                score = max(score, len(candidate))
        if score:
            priority = 1000 if job.status != STATUS_ARCHIVED else 0
            value = (priority + score, job)
            if best is None or value[0] > best[0]:
                best = value
    return best[1] if best else None


def _extract_top_n(text: str) -> int | None:
    match = re.search(r"前\s*([一二两三四五六七八九十\d]+)\s*(?:个|名|位)?", text)
    if not match:
        match = re.search(r"top\s*(\d+)", text, re.IGNORECASE)
    if not match:
        return None
    raw = match.group(1)
    if raw.isdigit():
        return max(1, min(int(raw), 10))
    return _CN_NUM.get(raw)


def _extract_min_years(text: str) -> int | None:
    match = re.search(r"(\d+)\s*年(?:以上)?", text)
    return int(match.group(1)) if match else None


def _extract_status(text: str) -> str | None:
    if re.search(r"淘汰|拒|不合适|不通过", text):
        return "rejected"
    if re.search(r"入职|录用", text):
        return "hired"
    if re.search(r"offer|发\s*offer", text, re.IGNORECASE):
        return "offer"
    if re.search(r"面试", text):
        return "interview"
    if re.search(r"筛选|初筛", text):
        return "screening"
    return None


def _extract_title(text: str) -> str | None:
    patterns = (
        r"(?:写|生成|做|起草|优化)(?:一个|一份|个)?\s*([A-Za-z0-9+#\u4e00-\u9fa5 ]{2,30}?)(?:的)?(?:JD|职位描述|岗位描述)",
        r"(?:JD|职位描述|岗位描述)(?:[:：]?\s*)([A-Za-z0-9+#\u4e00-\u9fa5 ]{2,30})",
        r"([A-Za-z0-9+#\u4e00-\u9fa5]{2,20}(?:工程师|开发|专员|经理|设计师|架构师|主管))",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            title = match.group(1).strip(" 的了，。,.！!")
            if title:
                return title
    return None


def _skill_in_text(name: str, text: str) -> bool:
    if not name:
        return False
    if re.search(r"[\u4e00-\u9fa5]", name):
        return name in text
    return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", text, re.IGNORECASE))


async def extract_slots(
    db: AsyncSession, text: str, session: ChatSession
) -> dict:
    """从话里 + 上下文中抽取槽位"""
    slots: dict = {}
    lowered = text.lower()

    # 职位：话里明确提到的优先，其次会话上下文
    jobs = list(
        (
            await db.execute(
                select(Job).where(Job.status != STATUS_ARCHIVED).order_by(Job.id.desc())
            )
        )
        .scalars()
        .all()
    )
    job = _match_job_in_text(jobs, text)
    if job is not None:
        slots["job_id"] = job.id
        slots["job_title"] = job.title
    elif session.context_job_id:
        slots["job_id"] = session.context_job_id
        current = next((row for row in jobs if row.id == session.context_job_id), None)
        if current is not None:
            slots["job_title"] = current.title

    # 候选人：全名匹配（取最长），其次会话上下文
    candidates = list(
        (
            await db.execute(
                select(Candidate)
                .where(Candidate.is_deleted.is_(False))
                .order_by(Candidate.id.desc())
                .limit(500)
            )
        )
        .scalars()
        .all()
    )
    named = sorted(
        (row for row in candidates if row.name and row.name in text),
        key=lambda row: len(row.name or ""),
        reverse=True,
    )
    if named:
        slots["candidate_id"] = named[0].id
        slots["candidate_name"] = named[0].name

    # 技能：按技能词表匹配（中英文都支持）
    skills = list((await db.execute(select(Skill).limit(800))).scalars().all())
    matched_skills: list[str] = []
    for skill in skills:
        names = [skill.name, *(skill.aliases or [])]
        if any(_skill_in_text(name, text) for name in names if name):
            matched_skills.append(skill.name)
    if matched_skills:
        slots["skills"] = list(dict.fromkeys(matched_skills))[:10]

    top_n = _extract_top_n(text)
    if top_n:
        slots["top_n"] = top_n
    min_years = _extract_min_years(text)
    if min_years is not None:
        slots["min_years"] = min_years

    status = _extract_status(text)
    if status:
        slots["to_status"] = status

    title = _extract_title(text)
    if title:
        slots["title"] = title

    # 应聘记录：由候选人 + 职位定位
    job_id = slots.get("job_id")
    candidate_id = slots.get("candidate_id") or session.context_candidate_id
    if candidate_id:
        slots.setdefault("candidate_id", candidate_id)
        target_candidate = next((row for row in candidates if row.id == candidate_id), None)
        if target_candidate is not None:
            slots.setdefault("candidate_name", target_candidate.name)
    if job_id and candidate_id:
        application = (
            await db.execute(
                select(Application)
                .where(
                    Application.job_id == job_id,
                    Application.candidate_id == candidate_id,
                )
                .order_by(Application.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if application is not None:
            slots["application_id"] = application.id
            slots["from_status"] = application.status

    if "全部" in text or "所有" in text:
        slots["all"] = True

    return slots


async def find_application(
    db: AsyncSession, candidate_id: int, job_id: int | None
) -> Application | None:
    conditions = [Application.candidate_id == candidate_id]
    if job_id:
        conditions.append(Application.job_id == job_id)
    return (
        await db.execute(
            select(Application)
            .where(*conditions)
            .order_by(Application.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
