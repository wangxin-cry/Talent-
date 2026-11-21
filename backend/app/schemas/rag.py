"""RAG 检索接口模型（阶段八）"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ResumeSearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=500, description="自然语言搜索词")
    top_k: int = Field(default=10, ge=1, le=50)
    job_id: int | None = Field(default=None, description="只搜该职位的投递者")
    exclude_candidate_id: int | None = None
    min_score: float | None = Field(default=None, ge=-1, le=1)


class ResumeHitOut(BaseModel):
    candidate_id: int
    name: str
    current_title: str = ""
    current_company: str = ""
    years_experience: float | None = None
    city: str | None = None
    skills: list[str] = Field(default_factory=list)
    score: float
    snippets: list[str] = Field(default_factory=list)


class ResumeSearchOut(BaseModel):
    query: str
    total: int
    available: bool
    items: list[ResumeHitOut] = Field(default_factory=list)


class RagHealthOut(BaseModel):
    enabled: bool
    index_enabled: bool
    backend: str
    embedding_configured: bool
    embedding_provider: str
    embedding_model: str
    dim: int
    collections: dict[str, int] = Field(default_factory=dict)


class RagConsistencyOut(BaseModel):
    consistent: bool
    expected: dict[str, int] = Field(default_factory=dict)
    actual: dict[str, int] = Field(default_factory=dict)
    mismatched: list[str] = Field(default_factory=list)


class ReindexOut(BaseModel):
    scope: str
    rebuilt: bool
    counts: dict[str, int] = Field(default_factory=dict)
