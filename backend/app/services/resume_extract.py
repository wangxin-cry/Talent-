"""
简历字段抽取：文本 → 固定结构 JSON

借鉴 gitee Resume-Assistant 的分层：
- 模型只负责"从文本里认字段"
- 归一化、置信度、字段级兜底全部由程序完成
"""
from __future__ import annotations

import re
from datetime import UTC, datetime

from loguru import logger

from app.core.config import settings
from app.services import llm

SYSTEM = "你是简历信息抽取器。只输出一个 JSON 对象，不要解释，不要 Markdown 围栏。"

TEMPLATE = """{
  "basic": {"name": "", "gender": "", "age": 0, "phone": "", "email": "",
            "city": "", "job_intention": "", "expected_salary": "",
            "highest_education": "", "years_experience": 0,
            "current_company": "", "current_title": ""},
  "education": [{"school": "", "major": "", "degree": "", "start": "", "end": ""}],
  "work": [{"company": "", "title": "", "employment_type": "", "start": "", "end": "", "description": ""}],
  "projects": [{"name": "", "role": "", "stack": [], "start": "", "end": "", "description": ""}],
  "skills": [],
  "certificates": []
}"""

PROMPT = """从下面的简历文本中抽取字段，严格遵守：

1. 只输出 JSON，字段名与结构必须和模板完全一致，不多不少
2. 抽不到的字段填 null（数组填 []）。**允许合理推断**：学历可从年龄 / 英语等级 / 大学生竞赛 / 校园职务推断；专业可从主修课程推断；推断出的字段正常填写，不要留 null。只有学校名称找不到时才填 null
3. 日期统一成 YYYY-MM（2023.09 / 2023年9月 / 2023-9 都写成 "2023-09"）；仍在校或在职写 "至今"
4. 保留原文语言，不要翻译、不要改写措辞
5. 学校、专业、学历 → education；公司任职（含实习、兼职）→ work；竞赛作品、课程设计、个人项目 → projects
6. work.description 与 projects.description 保留原文要点，用 "；" 连接，不要概括成一句话
7. projects.stack 与 skills 都输出**单个技能/技术关键词**数组（如 ["Python","FastAPI","Redis","Docker"]），一项一个词，不要整句描述
8. certificates 输出证书字符串数组（如 软件设计师、CET-6）
9. years_experience 为工作年限数字（年），没有全职工作但有实习填 0；有实习经历时 work 里要列出实习（employment_type 填 "实习"）
10. basic.city 是现居城市；current_company / current_title 是当前或最近一份工作
11. 若教育经历区块只写了"主修课程"没有学校/专业表头：从课程推断专业（如大量计算机课程→"计算机相关专业"），从年龄和学生身份推断学历（如 21岁+CET-4→"本科"），仍要在 education 数组里输出一条记录（school 可为 null）

模板：
{template}

简历内容：
{content}
"""

_DATE = re.compile(r"(\d{4})\s*[.\-/年]\s*(\d{1,2})")
_PHONE = re.compile(r"1[3-9]\d{9}")
# 兼容 139-5555-6666 / 139 5555 6666 / 139 5555-6666 等分隔写法
_PHONE_SEP = re.compile(r"1[3-9]\d[-\s]?\d{4}[-\s]?\d{4}")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_NAME_LINE = re.compile(r"^[\u4e00-\u9fa5·]{2,10}$")
_NAME_SKIP = {"个人简历", "简历", "求职简历", "基本信息", "个人信息", "联系方式"}


def _find_phone(text: str) -> str | None:
    """从文本中找手机号；带空格/横线的先归一成纯数字"""
    match = _PHONE.search(text)
    if match:
        return match.group(0)
    match = _PHONE_SEP.search(text)
    if match:
        digits = re.sub(r"\D", "", match.group(0))
        return digits if len(digits) == 11 else None
    return None


def _s(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _month(value) -> str | None:
    """2023.09 / 2023年9月 / 2023-9 → 2023-09；至今保留中文"""
    text = _s(value)
    if not text:
        return None
    if text.lower() in {"至今", "now", "present", "current"}:
        return "至今"
    match = _DATE.search(text)
    if not match:
        return text[:20]
    year, month = int(match.group(1)), int(match.group(2))
    return f"{year:04d}-{month:02d}" if 1 <= month <= 12 else str(year)


def _month_index(value: str | None) -> int | None:
    if not value:
        return None
    if value == "至今":
        now = datetime.now(UTC)
        return now.year * 12 + now.month
    match = _DATE.search(value)
    if not match:
        return None
    month = int(match.group(2))
    if not 1 <= month <= 12:
        return None
    return int(match.group(1)) * 12 + month


def _age(value) -> int | None:
    try:
        age = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return age if 14 <= age <= 80 else None


def _num(value) -> float | None:
    try:
        number = float(str(value).strip().rstrip("年"))
    except (TypeError, ValueError):
        return None
    return round(number, 1) if 0 <= number <= 50 else None


def _str_list(value) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := _s(item))]


def _years_from_work(rows: list[dict]) -> float | None:
    starts = [_month_index(row.get("start")) for row in rows]
    ends = [_month_index(row.get("end")) for row in rows]
    starts = [item for item in starts if item]
    ends = [item for item in ends if item]
    if not starts or not ends:
        return None
    months = max(ends) - min(starts)
    if months <= 0:
        return None
    return round(min(months / 12, 50), 1)


def normalize_payload(data: dict) -> dict:
    """收敛成固定结构：缺字段补 null/[]，模型多给的野字段直接丢弃"""
    if not isinstance(data, dict):
        data = {}
    basic_raw = data.get("basic") if isinstance(data.get("basic"), dict) else {}

    def rows(key: str, fields: tuple[str, ...]) -> list[dict]:
        raw_rows = data.get(key)
        if not isinstance(raw_rows, list):
            return []
        result: list[dict] = []
        for raw in raw_rows:
            if not isinstance(raw, dict):
                continue
            item: dict = {name: _s(raw.get(name)) for name in fields if name not in {"start", "end"}}
            if "start" in fields:
                item["start"] = _month(raw.get("start"))
            if "end" in fields:
                item["end"] = _month(raw.get("end"))
            if key == "projects":
                item["stack"] = _str_list(raw.get("stack"))
            if any(value for value in item.values() if value not in (None, [], "")):
                result.append(item)
        return result

    education = rows("education", ("school", "major", "degree", "start", "end"))
    work = rows("work", ("company", "title", "employment_type", "start", "end", "description"))
    projects = rows("projects", ("name", "role", "start", "end", "description"))

    basic = {
        "name": _s(basic_raw.get("name")),
        "gender": _s(basic_raw.get("gender")),
        "age": _age(basic_raw.get("age")),
        "phone": _s(basic_raw.get("phone")),
        "email": _s(basic_raw.get("email")),
        "city": _s(basic_raw.get("city") or basic_raw.get("location")),
        "job_intention": _s(basic_raw.get("job_intention")),
        "expected_salary": _s(basic_raw.get("expected_salary")),
        "highest_education": _s(basic_raw.get("highest_education")),
        "years_experience": _num(basic_raw.get("years_experience")),
        "current_company": _s(basic_raw.get("current_company")),
        "current_title": _s(basic_raw.get("current_title")),
    }
    if basic["years_experience"] is None:
        basic["years_experience"] = _years_from_work(work)

    return {
        "basic": basic,
        "education": education,
        "work": work,
        "projects": projects,
        "skills": _str_list(data.get("skills")),
        "certificates": _str_list(data.get("certificates")),
    }


def rule_based_payload(text: str) -> dict:
    """字段级兜底：模型不可用时用正则抽手机号/邮箱/姓名，保证仍能建档"""
    phone = _find_phone(text)
    email = _EMAIL.search(text)
    name = None
    for line in text.splitlines():
        candidate = line.strip()
        if candidate in _NAME_SKIP:
            continue
        if _NAME_LINE.fullmatch(candidate) and not candidate.endswith(("公司", "大学", "学院")):
            name = candidate
            break
    return normalize_payload({
        "basic": {
            "name": name,
            "phone": phone,
            "email": email.group(0) if email else None,
        },
        "education": [],
        "work": [],
        "projects": [],
        "skills": [],
        "certificates": [],
    })


def build_confidence(payload: dict, text: str, source: str) -> dict[str, float]:
    """字段置信度：前端 < 0.7 标黄；规则兜底整体压到 0.55"""
    basic = payload.get("basic") or {}
    confidence = {
        "name": 0.92 if basic.get("name") else 0.2,
        "phone": 0.95 if _PHONE.search(basic.get("phone") or "") else (0.55 if basic.get("phone") else 0.1),
        "email": 0.95 if _EMAIL.fullmatch(basic.get("email") or "") else (0.55 if basic.get("email") else 0.1),
        "city": 0.8 if basic.get("city") else 0.45,
        "education": 0.85 if payload.get("education") else 0.4,
        "work": 0.82 if payload.get("work") else (0.5 if ("工作" in text or "实习" in text) else 0.4),
        "skills": 0.8 if payload.get("skills") else 0.4,
        "current_company": 0.85 if basic.get("current_company") else 0.45,
        "current_title": 0.85 if basic.get("current_title") else 0.45,
        "years_experience": 0.7 if basic.get("years_experience") is not None else 0.4,
    }
    if source != "llm":
        confidence = {key: min(value, 0.55) for key, value in confidence.items()}
    return {key: round(value, 2) for key, value in confidence.items()}


# 课程关键词 → 专业推断
_MAJOR_KEYWORDS = [
    (["数据结构", "操作系统", "计算机网络", "计算机组成", "算法", "C语言", "Java", "Python程序"], "计算机相关专业"),
    (["高等数学", "线性代数", "概率论", "数学分析"], "数学相关专业"),
    (["大学物理", "电路", "模电", "数电", "信号与系统"], "电子信息相关专业"),
    (["机械设计", "工程力学", "材料力学"], "机械相关专业"),
    (["会计学", "财务管理", "经济学", "市场营销"], "经管相关专业"),
]
_STUDENT_HINTS = ("CET-4", "CET-6", "英语四级", "英语六级", "大学生", "校园", "班级", "助教", "学生会", "奖学金")


def _infer_education_from_text(payload: dict, text: str) -> tuple[dict, bool]:
    """
    LLM 未抽出学历/专业时的规则兜底：
    - 学历：从年龄 + 学生身份线索推断（18-25 岁且有 CET/大学生/校园 → 本科）
    - 专业：从主修课程关键词推断
    返回 (payload, 是否有推断)
    """
    basic = payload.get("basic") or {}
    education = list(payload.get("education") or [])
    inferred = False

    # --- 学历推断 ---
    has_degree = bool(basic.get("highest_education")) or any(
        (row or {}).get("degree") for row in education
    )
    if not has_degree:
        age = basic.get("age")
        is_student = any(hint in text for hint in _STUDENT_HINTS)
        degree = None
        if age is not None and 18 <= age <= 25 and is_student:
            degree = "本科"
        elif age is not None and 25 <= age <= 32:
            degree = "硕士"
        if degree:
            basic["highest_education"] = degree
            if education and not education[0].get("degree"):
                education[0]["degree"] = degree
            inferred = True

    # --- 专业推断 ---
    has_major = any((row or {}).get("major") for row in education)
    if not has_major:
        for keywords, major in _MAJOR_KEYWORDS:
            if sum(1 for kw in keywords if kw in text) >= 2:
                if education:
                    education[0]["major"] = major
                else:
                    education.append({"school": None, "major": major, "degree": basic.get("highest_education"),
                                      "start": None, "end": None})
                inferred = True
                break

    if inferred:
        payload["basic"] = basic
        payload["education"] = education
    return payload, inferred


async def extract_resume(text: str) -> tuple[dict, dict[str, float], dict]:
    """返回 (结构化 payload, 字段置信度, 元信息)；LLM 失败自动降级为规则抽取"""
    content = (text or "").strip()
    if not content:
        raise ValueError("简历内容为空")

    meta: dict = {"chars": len(content), "source": "llm"}
    payload: dict | None = None
    last_error: Exception | None = None

    for attempt in range(2):
        prompt = PROMPT.format(template=TEMPLATE, content=content[: settings.RESUME_MAX_CHARS])
        if attempt:
            prompt += "\n\n注意：上一次输出无法解析，请只输出一个合法 JSON 对象，不要任何解释。"
        try:
            result = await llm.chat_json(SYSTEM, prompt, temperature=0.1)
            payload = normalize_payload(llm.loads_json(result.text))
            meta.update({
                "model": result.model,
                "tokens": result.prompt_tokens + result.completion_tokens,
            })
            break
        except llm.LLMError as exc:
            last_error = exc
            logger.warning(f"简历抽取第 {attempt + 1} 次失败：{exc}")

    if payload is None:
        payload = rule_based_payload(content)
        meta.update({
            "source": "rule",
            "error": str(last_error)[:300] if last_error else "unknown",
        })
        logger.warning(f"简历抽取降级为规则兜底：{meta['error']}")

    # 规则兜底：LLM 未抽出学历/专业时，从年龄+课程+学生线索推断
    payload, inferred = _infer_education_from_text(payload, content)
    if inferred:
        meta["education_inferred"] = True

    confidence = build_confidence(payload, content, meta["source"])
    if inferred:
        # 推断出的学历/专业置信度压低，前端仍会标黄提示人工核对
        confidence["education"] = min(confidence.get("education", 0.5), 0.55)
    return payload, confidence, meta
