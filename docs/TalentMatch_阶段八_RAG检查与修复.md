# 阶段八 · RAG 知识增强：检查与修复记录

> 检查时间：2026-11-21　|　结论：**功能可用，但发现 5 个缺陷，已全部修复**
> 检查方式：读代码 + 真实链路验证（bge-m3 + faiss）+ 双环境全量测试

---

## 一、总体结论

阶段八的**设计实现质量高**：切片/索引/检索/降级/面试增强五条主线都完整，降级策略干净（异常内部吞掉，不影响主流程），
真实链路也跑通了（reindex 7.5s 建 14/4/24 条切片；`订单系统 Redis 缓存优化` → 张伟 0.726 正确召回）。

但存在 **5 个缺陷**，其中 3 个会让功能"看起来正常、实际静默失效"，已全部修复并补测试。

---

## 二、发现的缺陷与修复

### ① embedding 维度变化时，numpy 后端检索崩溃（P0）

| 项 | 内容 |
|---|---|
| 现象 | 换 embedding 模型（如 1024 维 → 其他维度）后，`numpy` 后端加载旧维度向量，`np.matmul` 抛 `ValueError`，语义搜索接口 500 |
| 对比 | `FaissStore` 有维度校验会安全重置，`NumpyStore` 没有 |
| 影响 | numpy 是**默认降级路径**（没装 faiss 的环境必走），一旦换模型全站搜索崩溃 |
| 修复 | `NumpyStore` 增加 `dim` 校验：加载时维度不符则丢弃索引并告警；`search` 时维度不符返回空 |
| 测试 | `test_vector_store.py::test_dimension_change_does_not_crash`（numpy/faiss 参数化） |

### ② faiss 后端从未被测试覆盖（P1）

| 项 | 内容 |
|---|---|
| 现象 | `test_rag.py` 固定 `VECTOR_BACKEND=numpy`，项目全部测试都在 numpy 上跑；faiss 是技术选型主路径却零覆盖 |
| 风险 | faiss 的 `IndexIDMap2` 增删改、持久化重载、维度保护都只靠"人工看过代码" |
| 修复 | 新增 `test_vector_store.py`（15 个用例）：参数化跑 numpy + faiss，覆盖增删查、幂等覆盖、持久化重载、维度变更、空库检索、**双后端排名一致性**、后端降级选择 |
| 效果 | 有 faiss 环境 15 passed；无 faiss 环境 8 passed + 1 skipped |

### ③ 向量库丢失后重建静默跳过（P0）

| 项 | 内容 |
|---|---|
| 现象 | 切换 `VECTOR_BACKEND`（`.npz` ↔ `.faiss`）、删索引目录后，`rag_chunk` 元数据还在，`_sync_scope` 判定"内容未变"全部跳过 → 向量永远是空，语义搜索静默返回 `[]` |
| 触发场景 | 从 py311（无 faiss，写 npz）切到 agent（有 faiss，读 faiss）——**本项目真实发生过** |
| 修复 | ① `_sync_scope` 检测到"该类型向量数为 0 但元数据存在"时强制重新向量化；② `reindex_all` 在 `rebuild=False` 时先做一致性检查，不一致自动升级为全量重建；③ 新增 `/rag/consistency` 接口暴露不一致 |
| 测试 | `test_rag.py::test_reindex_recovers_from_lost_index` |

### ④ `rebuild` 的 scope 与 doc_type 混用，重建不生效（P0）

| 项 | 内容 |
|---|---|
| 现象 | `reindex_all(scope="resumes", rebuild=True)` 里把 `"resumes"` 当 `doc_type` 用 → `vector_store.reset("resumes")`、`delete where doc_type="resumes"`，全部打空，"传了 rebuild 但什么都没清" |
| 后果 | 用户以为重建成功，实际旧向量旧元数据都在，且因③的跳过逻辑不会重算 |
| 修复 | 增加 `scope_to_doc` 映射（`resumes→resume` / `jobs→job` / `questions→question`），`all` 才展开三类 |
| 测试 | `test_rag.py::test_rebuild_scope_maps_to_doc_type`（验证重建 resumes 不影响 job 索引） |

### ⑤ `rag_sources` 未持久化，刷新页面参考来源消失（P1）

| 项 | 内容 |
|---|---|
| 现象 | 参考来源只放在生成响应里；`GET /applications/{id}/questions` 和指纹命中缓存路径都返回空 → 前端"知识库参考"面板消失 |
| 影响 | 演示时刷新一下页面，RAG 增强的可见证据就没了；命中缓存（省钱路径）反而看不到来源 |
| 修复 | `InterviewQuestion` 新增 `rag_sources` JSON 列；生成时随题目落库；`_to_set` 从首行还原 |
| 迁移 | 新增 `scripts/migrate_add_rag_sources.py`（幂等，SQLite/PG 双支持） |
| 测试 | `test_rag.py::test_rag_sources_persist_across_list_and_cache` |

### 附带优化：切片"万金油"问题（P2）

原实现把所有简历的全文摘要（600 字）塞进 `profile` 切片，导致它又长又泛，在所有查询上都拿高分，
真实项目片段被压在后面，展示出来的片段也多是"姓名：…；城市：…"这种低信息量内容。

修复：
- 有项目/经历明细时，`profile` 只保留基本信息，不再附带全文摘要；
- 检索结果片段按 `project > work > skills > profile` 排序展示。

效果：`订单系统 Redis 缓存优化` → 张伟 0.726，展示片段变为「公司：某电商科技；职位：高级后端工程师；描述：主导订单中心重构，落地 Redis 缓存与读写分离」。

---

## 三、环境问题（已解决）

| 项 | 现状 | 处理 |
|---|---|---|
| faiss 安装位置 | 只在 `conda:agent`（3.11.17, faiss 1.16.0）；`py311` 无 faiss | 后端改用 **agent** 解释器运行 |
| 配置与实际不符 | `.env`/默认配置写 `VECTOR_BACKEND=faiss`，但 py311 跑起来会静默降级 numpy | `scripts/dev-backend.ps1` 增加**解释器自动探测**：按"依赖齐全 + 有 faiss"打分选最优 |
| 历史索引格式 | `data/faiss/` 里是 `.npz`（py311 产物） | 切 faiss 后旧索引不被读取，已用 `reindex?rebuild=true` 重建为 `.faiss` |
| 脚本编码 | PowerShell 5.1 读无 BOM 的 UTF-8 中文脚本会解析失败 | `dev-backend.ps1` 改为**纯 ASCII 提示**，彻底免疫该问题 |

> 结论：**跑后端请用 `scripts/dev-backend.ps1`**，它会自动选到 agent 环境；手动启动时务必用 `conda:agent` 的 python。

---

## 四、真实链路验证结果

```
backend=faiss | embedding=BAAI/bge-m3 (1024 维) | dim 校验通过

全量重建  : 7.5s → resume 14 / job 4 / question 24
一致性    : consistent=true（expected == actual）
语义检索  : "订单系统 Redis 缓存优化" → 张伟 0.726（片段：主导订单中心重构…）
            "做过高并发订单系统"       → 张伟 0.609 / 王家豪 0.532
排除本人  : exclude_candidate_id 生效
索引丢失  : 删 resume.faiss → consistency 报 mismatched=[resume]
            → reindex(no rebuild) 自动全量重建 → 恢复 13 条 → 检索正常
面试题    : rag on  → source=llm_rag, rag_used=true, 6 条参考来源（2 简历 + 4 历史题）
            rag off → source=llm,      rag_used=false
            刷新页面 / 命中缓存 → rag_sources 仍能还原 6 条
```

---

## 五、测试结果

| 环境 | 结果 |
|---|---|
| `conda:agent`（含 faiss） | **76 passed** |
| `conda:py311`（无 faiss） | **69 passed, 1 skipped**（faiss 专属用例自动跳过） |

新增测试：
- `test_vector_store.py`：15 个（双后端参数化）
- `test_rag.py` 新增 4 个回归用例（rebuild 映射、索引丢失恢复、片段优先级、来源持久化）

---

## 六、仍存在的问题（未修，记录在案）

| 级别 | 问题 | 说明 / 建议 |
|:--:|---|---|
| P2 | 同岗位竞争者也出现在"相似候选人"参考里 | 当前只排除本人；面试参考用同岗位其他候选人价值有限，建议增加 `exclude_job_applicants` 选项 |
| P2 | 向量索引无版本标记 | 缺少"索引是基于哪版 EMBEDDING_MODEL 建的"元数据；换模型后靠维度判断，维度相同则无法发现 |
| P3 | `index_questions` 会清空重建整批题目切片 | 题目重新生成时旧切片通过 `chunk_key` 覆盖，逻辑正确但会产生一次额外 embedding |
| P3 | 职位 `submit/close/archive` 不触发索引 | 内容未变时影响不大；关闭职位仍在索引中，若未来用职位做检索需过滤状态 |
| P3 | `health()` 不含一致性状态 | 一致性在单独接口 `/rag/consistency`，可考虑合并到 health 便于监控 |
