"""RAG 检索接口（阶段八）"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.core.deps import CurrentUser, DbSession
from app.schemas.rag import (
    RagConsistencyOut,
    RagHealthOut,
    ReindexOut,
    ResumeHitOut,
    ResumeSearchIn,
    ResumeSearchOut,
)
from app.services import rag

router = APIRouter(prefix="/rag", tags=["RAG 知识增强"])


@router.get("/health", response_model=RagHealthOut, summary="RAG 运行状态")
async def rag_health() -> RagHealthOut:
    return RagHealthOut(**rag.health())


@router.get(
    "/consistency",
    response_model=RagConsistencyOut,
    summary="向量库与元数据一致性（切换后端后自检）",
)
async def rag_consistency(db: DbSession, _: CurrentUser) -> RagConsistencyOut:
    return RagConsistencyOut(**await rag.consistency(db))


@router.post("/search/resumes", response_model=ResumeSearchOut, summary="语义搜索人才库")
async def search_resumes(
    payload: ResumeSearchIn,
    db: DbSession,
    user: CurrentUser,
) -> ResumeSearchOut:
    hits = await rag.search_resumes(
        db,
        payload.query,
        top_k=payload.top_k,
        job_id=payload.job_id,
        exclude_candidate_id=payload.exclude_candidate_id,
        min_score=payload.min_score,
        user_id=user.id,
    )
    return ResumeSearchOut(
        query=payload.query,
        total=len(hits),
        available=rag.health()["enabled"] and rag.health()["embedding_configured"],
        items=[ResumeHitOut(**hit.__dict__) for hit in hits],
    )


@router.post("/reindex", response_model=ReindexOut, summary="重建向量索引（管理员）")
async def reindex(
    db: DbSession,
    user: CurrentUser,
    scope: str = Query(default="all", pattern="^(all|resumes|jobs|questions)$"),
    rebuild: bool = Query(default=False, description="先清空再重建"),
) -> ReindexOut:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅管理员可以重建向量索引",
        )
    counts = await rag.reindex_all(db, scope=scope, rebuild=rebuild)
    return ReindexOut(scope=scope, rebuilt=rebuild, counts=counts)
