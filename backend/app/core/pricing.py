"""LLM 计费单价（人民币 / 1K token）

单价集中在代码里维护，避免散落在业务逻辑中；按模型名精确匹配，
未收录的模型使用默认单价。调整单价不会改写历史 ai_call 记录。
"""
from __future__ import annotations

from app.core.config import settings

# 模型名 -> (输入单价, 输出单价)，单位：元 / 1K token
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "deepseek-ai/DeepSeek-V4-Flash": (0.001, 0.002),
    "deepseek-ai/DeepSeek-OCR": (0.001, 0.002),
    "Qwen/Qwen2.5-VL-72B-Instruct": (0.004, 0.012),
    # Embedding：SiliconFlow 的 bge-m3 当前免费；如供应商调价在此更新
    "BAAI/bge-m3": (0.0, 0.0),
}


def price_of(model: str | None) -> tuple[float, float]:
    """取模型单价，未收录时回落到全局默认"""
    if model and model in MODEL_PRICES:
        return MODEL_PRICES[model]
    return settings.LLM_PRICE_INPUT_PER_1K, settings.LLM_PRICE_OUTPUT_PER_1K


def estimate_cost(model: str | None, input_tokens: int, output_tokens: int) -> float:
    """按 token 数估算费用，保留 6 位小数"""
    input_price, output_price = price_of(model)
    cost = (max(0, input_tokens) / 1000) * input_price + (
        max(0, output_tokens) / 1000
    ) * output_price
    return round(cost, 6)
