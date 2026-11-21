"""
阶段八补充：向量存储后端测试

原 test_rag.py 全程用 VECTOR_BACKEND=numpy，faiss 路径零覆盖。
本文件直接针对 vector_store 两个后端做行为一致性验证：
1. 增删查与 count
2. 磁盘持久化与重载
3. embedding 维度变化时的自我保护（不能崩）
4. 幂等 upsert（同 id 覆盖不重复）
"""
from __future__ import annotations

import numpy as np
import pytest

from app.services import vector_store
from app.services.vector_store import FaissStore, NumpyStore

faiss_available = vector_store.faiss is not None
requires_faiss = pytest.mark.skipif(not faiss_available, reason="未安装 faiss-cpu")


def _make(backend: str, path, dim: int):
    if backend == "faiss":
        return FaissStore(path, dim)
    return NumpyStore(path, dim)


def _vec(seed: int, dim: int) -> list[float]:
    rng = np.random.default_rng(seed)
    raw = rng.normal(size=dim)
    norm = np.linalg.norm(raw)
    return (raw / norm).astype("float32").tolist()


BACKENDS = ["numpy"] + (["faiss"] if faiss_available else [])


# ---------------------------------------------------------------- 基础行为
@pytest.mark.parametrize("backend", BACKENDS)
def test_upsert_search_and_remove(backend, tmp_path):
    store = _make(backend, tmp_path / f"{backend}.idx", 16)

    a, b, c = _vec(1, 16), _vec(2, 16), _vec(3, 16)
    store.upsert([10, 20, 30], [a, b, c])
    assert store.count() == 3

    # 用 a 查询，命中 id=10 且分数最高（已归一化，内积=余弦）
    hits = store.search(a, 2)
    assert hits and hits[0][0] == 10
    assert hits[0][1] == pytest.approx(1.0, abs=1e-5)

    store.remove([10])
    assert store.count() == 2
    hits_after = store.search(a, 2)
    assert all(hit_id != 10 for hit_id, _ in hits_after)


@pytest.mark.parametrize("backend", BACKENDS)
def test_upsert_same_id_is_idempotent(backend, tmp_path):
    """同一 id 重复写入应覆盖而不是累加"""
    store = _make(backend, tmp_path / f"{backend}_idem.idx", 8)
    v1, v2 = _vec(1, 8), _vec(2, 8)

    store.upsert([1], [v1])
    store.upsert([1], [v2])
    assert store.count() == 1

    hits = store.search(v2, 1)
    assert hits[0][0] == 1


@pytest.mark.parametrize("backend", BACKENDS)
def test_persist_and_reload(backend, tmp_path):
    path = tmp_path / f"{backend}_persist.idx"
    store = _make(backend, path, 8)
    store.upsert([7], [_vec(7, 8)])
    store.persist()
    assert path.exists()

    reloaded = _make(backend, path, 8)
    assert reloaded.count() == 1
    hits = reloaded.search(_vec(7, 8), 1)
    assert hits[0][0] == 7


@pytest.mark.parametrize("backend", BACKENDS)
def test_reset_clears_index(backend, tmp_path):
    path = tmp_path / f"{backend}_reset.idx"
    store = _make(backend, path, 8)
    store.upsert([1, 2], [_vec(1, 8), _vec(2, 8)])
    store.reset()
    assert store.count() == 0
    store.persist()
    # 重置后落盘为空，重新加载也是空
    reloaded = _make(backend, path, 8)
    assert reloaded.count() == 0


@pytest.mark.parametrize("backend", BACKENDS)
def test_dimension_change_does_not_crash(backend, tmp_path):
    """
    embedding 模型尺寸变化后旧索引必须安全失效

    原实现下 numpy 后端会加载旧维度向量，检索时 np.matmul 抛 ValueError，
    把语义搜索接口打成 500；修复后应与 faiss 一致：丢弃并返回空。
    """
    path = tmp_path / f"{backend}_dim.idx"

    old = _make(backend, path, 8)
    old.upsert([1], [_vec(1, 8)])
    old.persist()

    # 模拟把 EMBEDDING_DIM 从 8 改成 16
    new = _make(backend, path, 16)
    assert new.count() == 0, "维度不一致时旧索引应被丢弃"
    assert new.search(_vec(2, 16), 3) == []


@pytest.mark.parametrize("backend", BACKENDS)
def test_search_on_empty_store_returns_empty(backend, tmp_path):
    store = _make(backend, tmp_path / f"{backend}_empty.idx", 8)
    assert store.search(_vec(1, 8), 5) == []
    assert store.count() == 0


# ---------------------------------------------------------------- 后端一致性
@requires_faiss
def test_numpy_and_faiss_agree_on_ranking(tmp_path):
    """同一批向量在两个后端上 top-k 顺序应一致（同为内积/余弦）"""
    dim = 32
    ids = list(range(1, 21))
    vectors = [_vec(i, dim) for i in ids]

    np_store = NumpyStore(tmp_path / "cmp.npz", dim)
    fs_store = FaissStore(tmp_path / "cmp.faiss", dim)
    np_store.upsert(ids, vectors)
    fs_store.upsert(ids, vectors)

    query = _vec(999, dim)
    np_hits = np_store.search(query, 5)
    fs_hits = fs_store.search(query, 5)

    assert [i for i, _ in np_hits] == [i for i, _ in fs_hits]
    for (_, s1), (_, s2) in zip(np_hits, fs_hits, strict=True):
        assert s1 == pytest.approx(s2, abs=1e-5)


# ---------------------------------------------------------------- 降级策略
def test_backend_falls_back_to_numpy_without_faiss(monkeypatch, tmp_path):
    """未安装 faiss 时必须自动降级 numpy，而不是报错"""
    monkeypatch.setattr(vector_store, "faiss", None)
    monkeypatch.setattr(vector_store.settings, "FAISS_DIR", str(tmp_path / "fb"))
    monkeypatch.setattr(vector_store.settings, "VECTOR_BACKEND", "auto")
    vector_store.reset_registry()
    try:
        assert vector_store.backend_name() == "numpy"
    finally:
        vector_store.reset_registry()


def test_backend_respects_explicit_numpy(monkeypatch, tmp_path):
    """显式指定 numpy 时即使装了 faiss 也用 numpy"""
    monkeypatch.setattr(vector_store.settings, "FAISS_DIR", str(tmp_path / "ex"))
    monkeypatch.setattr(vector_store.settings, "VECTOR_BACKEND", "numpy")
    vector_store.reset_registry()
    try:
        assert vector_store.backend_name() == "numpy"
    finally:
        vector_store.reset_registry()
