"""阶段八 RAG：切片、索引幂等、语义检索、降级与面试增强"""
from __future__ import annotations

import asyncio
import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.database import Base
from app.models.application import Application
from app.models.candidate import Candidate, Resume
from app.models.interview_question import InterviewQuestion
from app.models.job import Job
from app.models.rag_chunk import DOC_QUESTION, DOC_RESUME, RagChunk
from app.models.skill import Skill
from app.services import embeddings, interview_questions, rag, vector_store


def _configure(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "RAG_ENABLED", True)
    monkeypatch.setattr(settings, "RAG_INDEX_ENABLED", True)
    monkeypatch.setattr(settings, "VECTOR_BACKEND", "numpy")
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "mock")
    monkeypatch.setattr(settings, "EMBEDDING_DIM", 64)
    monkeypatch.setattr(settings, "FAISS_DIR", str(tmp_path / "vectors"))
    monkeypatch.setattr(settings, "RAG_MIN_SCORE", -1.0)
    monkeypatch.setattr(settings, "RAG_SIMILAR_RESUMES", 3)
    monkeypatch.setattr(settings, "RAG_SIMILAR_QUESTIONS", 3)
    vector_store.reset_registry()


async def _new_db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'rag.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed(factory):
    async with factory() as db:
        db.add_all(
            [
                Skill(name="Kafka", display_name="Kafka", category="middleware"),
                Skill(name="Flink", display_name="Flink", category="middleware"),
                Skill(name="Vue", display_name="Vue", category="framework"),
            ]
        )
        await db.flush()

        backend = Candidate(
            company_id=1,
            name="张伟",
            dedupe_key="manual:1",
            current_title="后端工程师",
            city="上海",
            years_experience=5,
            skills=["Kafka", "Flink", "Python"],
            resume_text="5 年后端经验，负责实时风控平台。",
        )
        frontend = Candidate(
            company_id=1,
            name="李娜",
            dedupe_key="manual:2",
            current_title="前端工程师",
            city="北京",
            years_experience=3,
            skills=["Vue", "TypeScript"],
            resume_text="3 年前端经验，负责管理后台。",
        )
        db.add_all([backend, frontend])
        await db.flush()

        db.add_all(
            [
                Resume(
                    company_id=1,
                    candidate_id=backend.id,
                    file_id=1,
                    structured={
                        "projects": [
                            {
                                "name": "实时风控平台",
                                "role": "核心开发",
                                "stack": ["Kafka", "Flink"],
                                "description": "使用 Kafka 与 Flink 构建实时风控引擎，日均处理十亿事件。",
                            }
                        ],
                        "work": [
                            {
                                "company": "某金融科技",
                                "title": "后端工程师",
                                "description": "负责风控规则引擎与实时计算。",
                            }
                        ],
                    },
                    content_hash="hash-backend",
                ),
                Resume(
                    company_id=1,
                    candidate_id=frontend.id,
                    file_id=2,
                    structured={
                        "projects": [
                            {
                                "name": "运营管理后台",
                                "role": "前端负责人",
                                "stack": ["Vue", "TypeScript"],
                                "description": "基于 Vue3 搭建运营管理后台与可视化图表。",
                            }
                        ],
                        "work": [
                            {
                                "company": "某互联网公司",
                                "title": "前端工程师",
                                "description": "负责中后台页面与组件库。",
                            }
                        ],
                    },
                    content_hash="hash-frontend",
                ),
            ]
        )

        job = Job(
            company_id=1,
            title="实时风控后端工程师",
            department="风控",
            location="上海",
            description="负责实时风控系统研发",
            requirements="熟悉 Kafka、Flink，有实时计算经验",
            skills=[1, 2],
            must_have_skills=[1],
            min_years=3,
            jd_version=1,
        )
        db.add(job)
        await db.flush()

        app_backend = Application(
            company_id=1,
            job_id=job.id,
            candidate_id=backend.id,
            status="new",
            source="manual",
        )
        app_frontend = Application(
            company_id=1,
            job_id=job.id,
            candidate_id=frontend.id,
            status="new",
            source="manual",
        )
        db.add_all([app_backend, app_frontend])
        await db.commit()
        return backend.id, frontend.id, job.id, app_backend.id, app_frontend.id


def test_chunk_index_idempotent_and_search(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    async def scenario():
        engine, factory = await _new_db(tmp_path)
        backend_id, frontend_id, job_id, _, _ = await _seed(factory)
        async with factory() as db:
            first = await rag.index_resume(db, backend_id)
            assert first >= 3
            count_before = (
                await db.execute(
                    select(func.count(RagChunk.id)).where(RagChunk.source_id == backend_id)
                )
            ).scalar_one()

            second = await rag.index_resume(db, backend_id)
            count_after = (
                await db.execute(
                    select(func.count(RagChunk.id)).where(RagChunk.source_id == backend_id)
                )
            ).scalar_one()
            assert second == first
            assert count_after == count_before

            await rag.index_resume(db, frontend_id)
            await rag.index_job(db, job_id)

            hits = await rag.search_resumes(db, "Kafka 实时风控", top_k=5)
            assert hits
            assert hits[0].candidate_id == backend_id
            assert hits[0].score > 0
            assert any(
                "Kafka" in snippet or "风控" in snippet for snippet in hits[0].snippets
            )

            excluded = await rag.search_resumes(
                db, "Kafka 实时风控", top_k=5, exclude_candidate_id=backend_id
            )
            assert all(hit.candidate_id != backend_id for hit in excluded)

            # 索引落盘后重新加载仍可检索
            vector_store.reset_registry()
            reloaded = await rag.search_resumes(db, "Kafka 实时风控", top_k=5)
            assert reloaded and reloaded[0].candidate_id == backend_id
        await engine.dispose()

    asyncio.run(scenario())


def test_interview_rag_toggle_and_sources(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    async def scenario():
        engine, factory = await _new_db(tmp_path)
        backend_id, _, job_id, app_backend_id, app_frontend_id = await _seed(factory)
        async with factory() as db:
            await rag.index_resume(db, backend_id)
            db.add(
                InterviewQuestion(
                    application_id=app_frontend_id,
                    job_id=job_id,
                    candidate_id=backend_id,
                    category="project",
                    question="请介绍你如何用 Kafka 做实时风控？",
                    looking_for="流处理经验",
                    reference="项目：实时风控平台",
                    follow_up="如何保证消息不丢？",
                    sort_order=0,
                    source="template",
                    fingerprint="seed",
                    company_id=1,
                )
            )
            await db.commit()
            await rag.index_questions(db, app_frontend_id)

            prompts: list[str] = []

            def fake_json_payload():
                questions = [
                    {
                        "category": "project",
                        "question": f"第{i + 1}题：请说明实时风控平台中 Kafka 的作用与取舍。",
                        "looking_for": "流处理与一致性",
                        "reference": "项目：实时风控平台",
                        "follow_up": "如果消息重复如何幂等？",
                    }
                    for i in range(8)
                ]
                return json.dumps({"questions": questions}, ensure_ascii=False)

            async def fake_chat_json(system_prompt, user_prompt, **kwargs):
                prompts.append(user_prompt)
                return type("R", (), {"text": fake_json_payload()})()

            monkeypatch.setattr(interview_questions.llm, "is_configured", lambda: True)
            monkeypatch.setattr(interview_questions.llm, "chat_json", fake_chat_json)

            application = await db.get(Application, app_backend_id)
            result = await interview_questions.generate_questions(
                db, application, use_llm=True, use_rag=True, force=True
            )
            assert 6 <= result.total <= 8
            assert result.rag_used is True
            assert result.source == "llm_rag"
            assert result.rag_sources
            assert "参考材料" in prompts[-1]

            no_rag = await interview_questions.generate_questions(
                db, application, use_llm=True, use_rag=False, force=True
            )
            assert no_rag.total == result.total
            assert no_rag.rag_used is False
            assert no_rag.source == "llm"
            assert "参考材料" not in prompts[-1]

            cached = await interview_questions.generate_questions(
                db, application, use_llm=True, use_rag=False
            )
            assert cached.cached is True
            assert cached.total == no_rag.total
        await engine.dispose()

    asyncio.run(scenario())


def test_template_works_with_and_without_rag(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    async def scenario():
        engine, factory = await _new_db(tmp_path)
        backend_id, _, _, app_backend_id, _ = await _seed(factory)
        async with factory() as db:
            await rag.index_resume(db, backend_id)
            application = await db.get(Application, app_backend_id)

            with_rag = await interview_questions.generate_questions(
                db, application, use_llm=False, use_rag=True, force=True
            )
            without_rag = await interview_questions.generate_questions(
                db, application, use_llm=False, use_rag=False, force=True
            )
            assert 6 <= with_rag.total <= 8
            assert 6 <= without_rag.total <= 8
            assert with_rag.source == "template"
            assert without_rag.source == "template"
        await engine.dispose()

    asyncio.run(scenario())


def test_embedding_failure_degrades_gracefully(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    async def scenario():
        engine, factory = await _new_db(tmp_path)
        backend_id, _, _, app_backend_id, _ = await _seed(factory)

        async def broken_embed(*args, **kwargs):
            raise embeddings.EmbeddingError("模拟向量服务不可用")

        monkeypatch.setattr(embeddings, "embed_texts", broken_embed)

        async with factory() as db:
            indexed = await rag.index_resume(db, backend_id)
            assert indexed == 0

            hits = await rag.search_resumes(db, "Kafka 实时风控")
            assert hits == []

            application = await db.get(Application, app_backend_id)
            result = await interview_questions.generate_questions(
                db, application, use_llm=False, use_rag=True, force=True
            )
            assert 6 <= result.total <= 8
            assert result.rag_used is False

            health = rag.health()
            assert health["backend"] in {"numpy", "faiss"}
            assert set(health["collections"]) == {DOC_RESUME, "job", DOC_QUESTION}
        await engine.dispose()

    asyncio.run(scenario())


# ---------------------------------------------------------------- 回归：索引一致性
def test_rebuild_scope_maps_to_doc_type(tmp_path, monkeypatch):
    """
    回归：scope 是复数（resumes/jobs/questions），doc_type 是单数（resume/job/...）

    早期实现把 scope 直接当 doc_type 用，rebuild 时 reset/delete 打了空集合，
    表现为"传了 rebuild=true 但什么都没清掉"。
    """
    _configure(tmp_path, monkeypatch)

    async def scenario():
        engine, factory = await _new_db(tmp_path)
        backend_id, frontend_id, job_id, _, _ = await _seed(factory)
        async with factory() as db:
            await rag.index_resume(db, backend_id)
            await rag.index_resume(db, frontend_id)
            await rag.index_job(db, job_id)

            before = await rag.consistency(db)
            assert before["actual"]["resume"] > 0
            assert before["actual"]["job"] > 0

            # 只重建简历：job 集合必须保持不变
            job_before = before["actual"]["job"]
            await rag.reindex_all(db, scope="resumes", rebuild=True)

            after = await rag.consistency(db)
            assert after["actual"]["resume"] == after["expected"]["resume"] > 0
            assert after["actual"]["job"] == job_before, "重建 resumes 不应清掉 job 索引"
            assert after["consistent"] is True
        await engine.dispose()

    asyncio.run(scenario())


def test_reindex_recovers_from_lost_index(tmp_path, monkeypatch):
    """
    回归：向量文件丢失（切换后端/删目录）后，增量 reindex 必须自动补回全部向量

    早期实现里 _sync_scope 按"内容未变就跳过"，元数据还在但向量为空时
    永远不会重新向量化，语义搜索静默返回空。
    """
    _configure(tmp_path, monkeypatch)

    async def scenario():
        engine, factory = await _new_db(tmp_path)
        backend_id, frontend_id, job_id, _, _ = await _seed(factory)

        async with factory() as db:
            await rag.index_resume(db, backend_id)
            await rag.index_resume(db, frontend_id)
            await rag.index_job(db, job_id)

            full = await rag.consistency(db)
            assert full["consistent"] is True
            expected_resume = full["expected"]["resume"]
            assert expected_resume > 0

        # 模拟 resume 索引文件丢失：清空内存索引并删掉落盘文件
        vector_store.reset_registry()
        (tmp_path / "vectors" / "resume.npz").unlink(missing_ok=True)

        async with factory() as db:
            lost = await rag.consistency(db)
            assert lost["consistent"] is False
            assert lost["actual"]["resume"] == 0
            assert lost["expected"]["resume"] == expected_resume

            # 不传 rebuild，也应自动升级为全量重建
            await rag.reindex_all(db, scope="resumes", rebuild=False)

            recovered = await rag.consistency(db)
            assert recovered["actual"]["resume"] == expected_resume
            assert recovered["consistent"] is True

            hits = await rag.search_resumes(db, "Kafka 实时风控", top_k=5)
            assert hits and hits[0].candidate_id == backend_id
        await engine.dispose()

    asyncio.run(scenario())


def test_search_snippets_prefer_project_and_work(tmp_path, monkeypatch):
    """片段必须优先展示项目/经历，而不是又长又泛的基本信息切片"""
    _configure(tmp_path, monkeypatch)

    async def scenario():
        engine, factory = await _new_db(tmp_path)
        backend_id, _, _, _, _ = await _seed(factory)
        async with factory() as db:
            await rag.index_resume(db, backend_id)
            hits = await rag.search_resumes(db, "Kafka 实时风控平台", top_k=1)
            assert hits
            snippet = hits[0].snippets[0]
            assert not snippet.startswith("姓名："), snippet
            assert ("项目：" in snippet) or ("公司：" in snippet), snippet
        await engine.dispose()

    asyncio.run(scenario())


def test_rag_sources_persist_across_list_and_cache(tmp_path, monkeypatch):
    """
    回归：rag_sources 必须落库

    早期只把参考来源放在生成响应里，页面刷新（走 GET）或指纹命中缓存时
    返回空列表，前端"知识库参考"面板直接消失。
    """
    _configure(tmp_path, monkeypatch)

    async def scenario():
        engine, factory = await _new_db(tmp_path)
        backend_id, _, job_id, app_backend_id, app_frontend_id = await _seed(factory)

        async def fake_chat_json(system_prompt, user_prompt, **kwargs):
            questions = [
                {
                    "category": "project",
                    "question": f"第{i + 1}题：实时风控平台中 Kafka 如何保证不丢消息？",
                    "looking_for": "流处理一致性",
                    "reference": "项目：实时风控平台",
                    "follow_up": "如何做幂等？",
                }
                for i in range(8)
            ]
            return type("R", (), {"text": json.dumps({"questions": questions}, ensure_ascii=False)})()

        async with factory() as db:
            await rag.index_resume(db, backend_id)
            db.add(
                InterviewQuestion(
                    application_id=app_frontend_id,
                    job_id=job_id,
                    candidate_id=backend_id,
                    category="project",
                    question="请介绍你如何用 Kafka 做实时风控？",
                    looking_for="流处理经验",
                    reference="项目：实时风控平台",
                    follow_up="如何保证消息不丢？",
                    sort_order=0,
                    source="template",
                    fingerprint="seed",
                    company_id=1,
                )
            )
            await db.commit()
            await rag.index_questions(db, app_frontend_id)

            monkeypatch.setattr(interview_questions.llm, "is_configured", lambda: True)
            monkeypatch.setattr(interview_questions.llm, "chat_json", fake_chat_json)

            application = await db.get(Application, app_backend_id)
            generated = await interview_questions.generate_questions(
                db, application, use_llm=True, use_rag=True, force=True
            )
            assert generated.source == "llm_rag"
            assert generated.rag_sources

            # 走 GET 列表（页面刷新）：参考来源必须还原
            listed = await interview_questions.list_questions(db, application)
            assert listed.source == "llm_rag"
            assert listed.rag_used is True
            assert len(listed.rag_sources) == len(generated.rag_sources)
            assert listed.rag_sources[0]["type"] in {"resume", "question"}

            # 走缓存命中：同样要还原
            cached = await interview_questions.generate_questions(
                db, application, use_llm=True, use_rag=True
            )
            assert cached.cached is True
            assert len(cached.rag_sources) == len(generated.rag_sources)
        await engine.dispose()

    asyncio.run(scenario())
