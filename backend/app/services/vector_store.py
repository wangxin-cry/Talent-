"""
向量存储适配层（阶段八）

优先使用 FAISS（进程内、磁盘持久化）；未安装 faiss-cpu 时自动降级为
numpy 精确检索，保证 RAG 功能可用、业务不中断。
"""
from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path
from typing import Protocol

import numpy as np
from loguru import logger

from app.core.config import settings

try:  # faiss-cpu 未安装时保留 numpy 方案
    import faiss  # type: ignore
except Exception:  # pragma: no cover - 取决于运行环境
    faiss = None


class _Store(Protocol):
    def upsert(self, ids: list[int], vectors: list[list[float]]) -> None: ...
    def remove(self, ids: list[int]) -> None: ...
    def search(self, vector: list[float], top_k: int) -> list[tuple[int, float]]: ...
    def count(self) -> int: ...
    def reset(self) -> None: ...
    def persist(self) -> None: ...


class NumpyStore:
    """暴力内积检索；几千条数据足够，同时作为 FAISS 的兜底"""

    def __init__(self, path: Path, dim: int | None = None):
        self.path = path
        self.dim = dim
        self._vectors: dict[int, np.ndarray] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with np.load(self.path) as data:
                ids = data["ids"].tolist()
                vectors = data["vectors"]
                stored_dim = int(data["dim"]) if "dim" in data.files else None
            if self.dim is None:
                self.dim = stored_dim
            elif stored_dim is not None and stored_dim != self.dim:
                # 与 FAISS 的行为对齐：维度不一致时丢弃旧索引，从空开始。
                # 不丢弃会让后续检索在 np.matmul 处抛 ValueError，把搜索接口打成 500。
                logger.warning(
                    "numpy 索引维度 {} 与配置 {} 不一致，已丢弃旧索引（需重建）",
                    stored_dim,
                    self.dim,
                )
                self._vectors = {}
                return
            if self.dim is not None and len(vectors) and vectors.shape[1] != self.dim:
                logger.warning(
                    "numpy 索引向量维度 {} 与配置 {} 不一致，已丢弃旧索引（需重建）",
                    vectors.shape[1],
                    self.dim,
                )
                self._vectors = {}
                return
            self._vectors = {
                int(i): np.asarray(vec, dtype="float32")
                for i, vec in zip(ids, vectors, strict=False)
            }
        except Exception as exc:  # 索引损坏时从空开始
            logger.warning("加载 numpy 向量索引失败 {}：{}", self.path, exc)
            self._vectors = {}

    def upsert(self, ids: list[int], vectors: list[list[float]]) -> None:
        for i, vec in zip(ids, vectors, strict=False):
            if self.dim is None:
                self.dim = len(vec)
            self._vectors[int(i)] = np.asarray(vec, dtype="float32")

    def remove(self, ids: list[int]) -> None:
        for i in ids:
            self._vectors.pop(int(i), None)

    def search(self, vector: list[float], top_k: int) -> list[tuple[int, float]]:
        if not self._vectors:
            return []
        if self.dim is not None and len(vector) != self.dim:
            # 查询向量维度不符说明索引已过期，直接返回空，由上层触发重建
            logger.warning(
                "查询向量维度 {} 与索引维度 {} 不一致，跳过检索（请重建索引）",
                len(vector),
                self.dim,
            )
            return []
        ids = list(self._vectors.keys())
        matrix = np.stack([self._vectors[i] for i in ids])
        query = np.asarray(vector, dtype="float32")
        scores = matrix @ query
        limit = min(max(1, top_k), len(ids))
        top = np.argpartition(-scores, limit - 1)[:limit]
        top = top[np.argsort(-scores[top])]
        return [(ids[int(i)], float(scores[int(i)])) for i in top]

    def count(self) -> int:
        return len(self._vectors)

    def reset(self) -> None:
        self._vectors = {}

    def persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        if not self._vectors:
            self.path.unlink(missing_ok=True)
            return
        ids = np.asarray(list(self._vectors.keys()), dtype="int64")
        matrix = np.stack([self._vectors[i] for i in ids.tolist()])
        with open(tmp, "wb") as handle:
            np.savez(handle, ids=ids, vectors=matrix, dim=np.asarray(self.dim or matrix.shape[1]))
        os.replace(tmp, self.path)


class FaissStore:
    """IndexIDMap2 + Inner Product；向量已归一化，等价余弦相似度"""

    def __init__(self, path: Path, dim: int):
        self.path = path
        self.dim = dim
        self._index = self._new_index()
        self._load()

    def _new_index(self):
        return faiss.IndexIDMap2(faiss.IndexFlatIP(self.dim))

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            loaded = faiss.read_index(str(self.path))
            if loaded.d != self.dim:
                raise ValueError(f"索引维度 {loaded.d} 与配置 {self.dim} 不一致")
            self._index = loaded
        except Exception as exc:
            logger.warning("加载 FAISS 索引失败 {}：{}", self.path, exc)
            self._index = self._new_index()

    def upsert(self, ids: list[int], vectors: list[list[float]]) -> None:
        if not ids:
            return
        if self._index.ntotal:
            self._index.remove_ids(np.asarray(ids, dtype="int64"))
        matrix = np.asarray(vectors, dtype="float32")
        self._index.add_with_ids(matrix, np.asarray(ids, dtype="int64"))

    def remove(self, ids: list[int]) -> None:
        if ids and self._index.ntotal:
            self._index.remove_ids(np.asarray(ids, dtype="int64"))

    def search(self, vector: list[float], top_k: int) -> list[tuple[int, float]]:
        if not self._index.ntotal:
            return []
        query = np.asarray([vector], dtype="float32")
        scores, ids = self._index.search(query, min(max(1, top_k), self._index.ntotal))
        return [
            (int(i), float(s))
            for i, s in zip(ids[0].tolist(), scores[0].tolist(), strict=False)
            if int(i) >= 0
        ]

    def count(self) -> int:
        return int(self._index.ntotal)

    def reset(self) -> None:
        self._index = self._new_index()

    def persist(self) -> None:
        if faiss is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        faiss.write_index(self._index, str(tmp))
        os.replace(tmp, self.path)


class _State:
    def __init__(self, backend: str, store: _Store):
        self.backend = backend
        self.store = store
        self.lock = threading.RLock()


_states: dict[str, _State] = {}
_registry_lock = threading.Lock()
_fallback_warned = False


def _preferred_backend() -> str:
    mode = (settings.VECTOR_BACKEND or "auto").lower()
    global _fallback_warned
    if mode == "numpy":
        return "numpy"
    if faiss is not None:
        return "faiss"
    if not _fallback_warned:
        logger.warning("未安装 faiss-cpu，向量检索自动降级为 numpy（pip install faiss-cpu 可启用）")
        _fallback_warned = True
    return "numpy"


def _state(doc_type: str) -> _State:
    backend = _preferred_backend()
    directory = Path(settings.FAISS_DIR)
    suffix = ".faiss" if backend == "faiss" else ".npz"
    path = directory / f"{doc_type}{suffix}"

    with _registry_lock:
        current = _states.get(doc_type)
        if current is not None and current.backend == backend:
            store_path = getattr(current.store, "path", None)
            if store_path == path:
                return current
        store: _Store = (
            FaissStore(path, settings.EMBEDDING_DIM)
            if backend == "faiss"
            else NumpyStore(path, settings.EMBEDDING_DIM)
        )
        current = _State(backend, store)
        _states[doc_type] = current
        return current


def reset_registry() -> None:
    """切换目录或测试隔离时丢弃内存索引"""
    with _registry_lock:
        _states.clear()


def backend_name() -> str:
    return _preferred_backend()


def count(doc_type: str) -> int:
    return _state(doc_type).store.count()


def _persisting_upsert(state: _State, ids: list[int], vectors: list[list[float]]) -> None:
    with state.lock:
        state.store.upsert(ids, vectors)
        state.store.persist()


def _persisting_remove(state: _State, ids: list[int]) -> None:
    with state.lock:
        state.store.remove(ids)
        state.store.persist()


def _searching(state: _State, vector: list[float], top_k: int) -> list[tuple[int, float]]:
    with state.lock:
        return state.store.search(vector, top_k)


async def upsert(doc_type: str, ids: list[int], vectors: list[list[float]]) -> None:
    if not ids:
        return
    state = _state(doc_type)
    await asyncio.to_thread(_persisting_upsert, state, ids, vectors)


async def remove(doc_type: str, ids: list[int]) -> None:
    if not ids:
        return
    state = _state(doc_type)
    await asyncio.to_thread(_persisting_remove, state, ids)


async def search(doc_type: str, vector: list[float], top_k: int) -> list[tuple[int, float]]:
    state = _state(doc_type)
    return await asyncio.to_thread(_searching, state, vector, top_k)


async def reset(doc_type: str) -> None:
    state = _state(doc_type)
    with state.lock:
        state.store.reset()
        state.store.persist()
