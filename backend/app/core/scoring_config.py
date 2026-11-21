"""
匹配打分权重配置（对应 docs A.1 公式）

final = 100 * (0.50*skill + 0.30*exp + 0.12*edu + 0.08*other)

权重集中在此处，标注集调参时只改这一个文件。
"""
from __future__ import annotations

from pydantic_settings import BaseSettings

# 打分算法版本：特征/公式改动时手动 +1，旧缓存自动失效
SCORING_VERSION = "2026.11.1"

class ScoringConfig(BaseSettings):
    # 综合权重（四类相加 = 1.0）
    W_SKILL: float = 0.50
    W_EXP: float = 0.30
    W_EDU: float = 0.12
    W_OTHER: float = 0.08

    # 技能分内部权重
    SKILL_MUST_WEIGHT: float = 0.7       # must-have 覆盖率权重
    SKILL_NICE_WEIGHT: float = 0.3       # nice-to-have 覆盖率权重
    SKILL_MISS_PENALTY: float = 0.6      # 缺任一 must-have 时整体乘此惩罚系数

    # 经验分上限分配
    EXP_YEARS_CAP: float = 0.6           # 年限达标上限
    EXP_RELEVANCE_CAP: float = 0.3       # 相关领域加分上限
    EXP_STABILITY_CAP: float = 0.1       # 稳定性加分上限

    # 学历分
    EDU_MEET: float = 1.0
    EDU_OVER: float = 0.9
    EDU_BELOW: float = 0.5

    # 其他分
    OTHER_LOCATION_W: float = 0.5
    OTHER_SALARY_W: float = 0.3
    OTHER_INDUSTRY_W: float = 0.2

    # 学历等级排序（数字越大越高）
    EDU_RANK: dict[str, int] = {
        "college": 1,
        "bachelor": 2,
        "master": 3,
        "phd": 4,
    }

    model_config = {"env_prefix": "SCORING_", "extra": "ignore"}


scoring = ScoringConfig()
