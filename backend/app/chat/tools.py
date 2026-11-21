"""对话工具注册表（阶段九½）

把阶段三~七的能力统一封装成「带说明 + 参数 schema」的工具：
- read：确定性查询 / 生成，直接执行；
- write：受控写，先出执行计划再确认；
- irreversible：不可逆写，强制二次确认 + 展示影响面。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

LEVEL_READ = "read"
LEVEL_WRITE = "write"
LEVEL_IRREVERSIBLE = "irreversible"

LEVEL_LABELS = {
    LEVEL_READ: "读 / 生成（直接执行）",
    LEVEL_WRITE: "受控写（先出计划）",
    LEVEL_IRREVERSIBLE: "不可逆写（强制确认）",
}


def _schema(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


@dataclass
class ToolDef:
    name: str
    label: str
    description: str
    level: str
    parameters: dict = field(default_factory=dict)


TOOLS: dict[str, ToolDef] = {
    "parse_resume": ToolDef(
        name="parse_resume",
        label="解析简历",
        description="把已上传的 PDF/DOCX 简历逐份解析入库；单份失败不影响整批。",
        level=LEVEL_WRITE,
        parameters=_schema(
            {
                "file_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "指定简历文件 id；为空则解析待处理/失败的文件",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "description": "批量解析上限",
                },
            }
        ),
    ),
    "search_candidates": ToolDef(
        name="search_candidates",
        label="人才库检索",
        description="按关键词、技能、最低工作年限检索候选人（确定性查询，不调 LLM）。",
        level=LEVEL_READ,
        parameters=_schema(
            {
                "q": {"type": "string", "description": "姓名 / 公司 / 职位关键词"},
                "skills": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "技能名，如 Go、Python",
                },
                "min_years": {"type": "number", "description": "最低工作年限"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            }
        ),
    ),
    "match_job": ToolDef(
        name="match_job",
        label="人岗匹配",
        description="对指定职位匹配全库候选人，返回可解释排名（规则算分 + 理由）。",
        level=LEVEL_READ,
        parameters=_schema(
            {
                "job_id": {"type": "integer", "description": "职位 id"},
                "top_n": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            required=["job_id"],
        ),
    ),
    "generate_interview": ToolDef(
        name="generate_interview",
        label="生成面试题",
        description="为指定候选人（或匹配前 N 名）生成带考察点的面试题。",
        level=LEVEL_READ,
        parameters=_schema(
            {
                "job_id": {"type": "integer", "description": "职位 id"},
                "candidate_id": {"type": "integer", "description": "候选人 id"},
                "application_id": {"type": "integer", "description": "应聘记录 id"},
                "top_n": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            required=["job_id"],
        ),
    ),
    "generate_jd": ToolDef(
        name="generate_jd",
        label="生成 JD",
        description="根据职位名 + 关键词生成可编辑的三段 JD 草稿。",
        level=LEVEL_READ,
        parameters=_schema(
            {
                "title": {"type": "string", "description": "职位名称"},
                "job_id": {"type": "integer", "description": "已有职位 id"},
                "keywords": {"type": "array", "items": {"type": "string"}},
            }
        ),
    ),
    "query_analytics": ToolDef(
        name="query_analytics",
        label="查看看板数据",
        description="查询漏斗、渠道、招聘周期等统计数据，并给出一句洞察。",
        level=LEVEL_READ,
        parameters=_schema(
            {
                "dimension": {
                    "type": "string",
                    "enum": ["overview", "funnel", "channels", "cycle", "all"],
                }
            }
        ),
    ),
    "get_application_status": ToolDef(
        name="get_application_status",
        label="查候选人进度",
        description="查询候选人在某个职位上的当前状态、匹配分与停留天数。",
        level=LEVEL_READ,
        parameters=_schema(
            {
                "application_id": {"type": "integer"},
                "candidate_id": {"type": "integer"},
                "job_id": {"type": "integer"},
            }
        ),
    ),
    "publish_job": ToolDef(
        name="publish_job",
        label="发布职位",
        description="发布一个草稿职位；执行前必须先展示发布计划并确认。",
        level=LEVEL_WRITE,
        parameters=_schema(
            {"job_id": {"type": "integer", "description": "职位 id"}},
            required=["job_id"],
        ),
    ),
    "advance_status": ToolDef(
        name="advance_status",
        label="推进候选人状态",
        description="推进候选人到下一阶段；不可逆，必须二次确认并校验状态机。",
        level=LEVEL_IRREVERSIBLE,
        parameters=_schema(
            {
                "application_id": {"type": "integer"},
                "to_status": {
                    "type": "string",
                    "enum": ["screening", "interview", "offer", "hired"],
                },
                "note": {"type": "string"},
            },
            required=["application_id", "to_status"],
        ),
    ),
    "reject_candidate": ToolDef(
        name="reject_candidate",
        label="淘汰候选人",
        description="淘汰候选人；不可逆，必须二次确认且必填原因。",
        level=LEVEL_IRREVERSIBLE,
        parameters=_schema(
            {
                "application_id": {"type": "integer"},
                "note": {"type": "string", "description": "淘汰原因（必填）"},
            },
            required=["application_id", "note"],
        ),
    ),
}


def tool_table() -> list[dict]:
    return [
        {
            "name": tool.name,
            "label": tool.label,
            "description": tool.description,
            "level": tool.level,
            "parameters": tool.parameters,
        }
        for tool in TOOLS.values()
    ]


def tool_prompt() -> str:
    """给 LLM 的工具清单（function calling 的简化版）"""
    return json.dumps(tool_table(), ensure_ascii=False, indent=2)
