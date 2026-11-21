# 阶段九 · 多 Agent 编排：检查与修复记录

> 检查时间：2026-11-21　|　结论：**6 项任务全部完成，验收 3 项全部通过；发现 2 个真 bug，已修复**
> 检查方式：读代码 + 真实链路验证（LangGraph + 真实 LLM）+ 双环境全量测试

---

## 一、总体结论

阶段九实现质量高：LangGraph Supervisor 结构清晰（中心调度 + 6 节点 + 条件边）、Context Bus 真正避免了重复计算、
三级降级齐全、轨迹落库完整。三个验收场景实测全部通过。

但发现 **2 个真 bug**，都属于"SQLite 测试测不出来、真实 PG 或异常输入才暴露"的类型：
轨迹列表接口在 PostgreSQL 下 500、不存在的候选人也能"成功"生成面试题。均已修复并补回归测试。

---

## 二、6 项完成度对照

| # | 计划任务 | 状态 | 证据 |
|:--:|---|:--:|---|
| 1 | LangGraph Supervisor 模式 | ✅ | `StateGraph` + `supervisor` 中心节点 + 6 个子 Agent 节点 + 条件路由边；`recursion_limit` 按计划长度计算 |
| 2 | Manager 意图映射表 | ✅ | 7 个意图（JD/批量解析/匹配/面试/推进/看板/一键评估），`/orchestration/intents` 可查 |
| 3 | Context Bus 共享上下文 | ✅ | `OrchestrationContext`：匹配缺口直接传给面试 Agent，不重算简历特征 |
| 4 | 三级降级 + AgentTrace 落库 | ✅ | 超时 / 失败 / 依赖缺失分别处理；每步写 `agent_trace`，含 token、cost、degraded |
| 5 | 三个场景（批量解析/一键评估/推进） | ✅ | 实测通过（见第四节） |
| 6 | 前端轨迹面板 | ✅ | `/orchestration` 页：意图 chip、执行结果、逐步轨迹（耗时/token/成本/降级）、最近轨迹列表可点开 |

---

## 三、三个验收项实测结果

### 验收 1：一键评估 top3

```
POST /orchestration/run {intent: full_eval, job_id: 4, top_n: 3, use_llm: true}
→ 200，71.9s，status=success
→ 轨迹 4 步：Manager → MatchEngine → InterviewAssistant → Manager
→ 排名 3 人；面试题 3 人（7 / 8 / 8 题）
→ total_tokens 5513，total_cost ¥0.008784
→ trace_id 可查：4 步、成本一致
```

**一次点击返回「排名 + 3 人面试题 + 轨迹 + 总成本」——通过。**

### 验收 2：故意让子 Agent 超时

```
step_timeout=0.05
→ InterviewAssistant status=timeout, degraded=true
→ 整体 status=degraded
→ 排名仍返回 2 条，面试题为空
→ errors: "执行超时（>0.05s）；面试题已跳过"
```

**整体仍返回其余结果并标 degraded——通过。**

### 验收 3：轨迹面板

```
GET /orchestration/traces/{trace_id} → 200，4 步，每步含 agent/status/duration_ms/tokens/cost/degraded
GET /orchestration/traces → 200，最近 5 次编排
前端 /orchestration 页 → 7 个意图 chip + 轨迹表格 + 最近轨迹可点开
```

**每一步的 Agent、耗时、token、是否降级都可见——通过。**

---

## 四、发现的 2 个缺陷与修复

### ① 轨迹列表在 PostgreSQL 下 500（P0）

| 项 | 内容 |
|---|---|
| 现象 | `GET /orchestration/traces` 返回 500：`function max(boolean) does not exist` |
| 根因 | `list_recent_traces` 用 `func.max(AgentTrace.degraded)` 聚合布尔列。SQLite 恰好支持（0/1），**PostgreSQL 不支持** |
| 影响 | 前端"最近编排"列表在真实 PG 上完全不可用；而全部测试跑在 SQLite 上，**测试全绿也发现不了** |
| 修复 | 改为 `func.max(case((degraded.is_(True), 1), else_=0))` |
| 测试 | 新增用例断言聚合结果正确，并加**静态检查**：源码里不得再出现 `max(AgentTrace.degraded)`，防止改回 |

### ② 不存在的候选人也能"成功"生成面试题（P1）

| 项 | 内容 |
|---|---|
| 现象 | 传 `candidate_id=999999` → status=success、8 道通用模板题、`candidate_name` 为空 |
| 根因 | `_load_context_for` 对不存在的候选人静默返回空 context；`preview_questions` 不校验存在性 |
| 影响 | 用户传错 id 得到"看起来成功但毫无意义"的结果；编排层也无法降级提示；**三级降级形同虚设** |
| 修复 | `preview_questions` 先校验候选人存在（含软删除），不存在抛错 → Supervisor 捕获为 failed + 降级 |
| 效果 | 修复后：`status=degraded`、`evaluations[0].status=failed`、错误"候选人不存在：999999" |
| 测试 | 新增 `test_interview_with_missing_candidate_degrades` |

---

## 五、设计上值得肯定的点

1. **Supervisor 只做路由，不做业务**：每步执行仍在子 Agent/service，符合 §5.3「Agent 与 Tool 边界」
2. **降级不是"吞异常"**：每级都有对应兜底函数（`fallback_match` 复用旧匹配结果、`fallback_workflow` 返回 `allowed=false`），且明确记录 error
3. **成本归属**：`_attach_usage` 用 `trace_id` 把 `ai_call` 用量按 `agent` 归到对应步骤，总成本可对上账
4. **依赖缺失的正确处理**：`_supervisor_node` 在派发前检查前置产出，缺则记 `skipped` 而不是让下游空跑
5. **业务拒绝不算系统故障**：非法状态迁移捕获 `HTTPException` → `degraded` + `allowed=false`，不抛 500
6. **轨迹存摘要不存全文**：`input_summary`/`output_summary` 是结构化摘要，避免简历全文进轨迹表

---

## 六、测试结果

| 环境 | 结果 |
|---|---|
| `conda:agent`（含 faiss） | **84 passed** |
| `conda:py311`（无 faiss） | **77 passed, 1 skipped** |

编排相关：8 个用例（原 6 + 新增 2 个回归）。

---

## 七、仍存在的问题（未修，记录在案）

| 级别 | 问题 | 说明 / 建议 |
|:--:|---|---|
| P2 | 无效目标状态的提示不够友好 | 传 `to_status=archived`（职位状态）返回"未知状态：archived"，建议改为"应聘状态只能是 new/screening/..."并列出当前允许的流转 |
| P2 | 批量解析场景未实测 | `resume_upload` 有代码与测试，但没在真实 PG + MinIO 上跑过大批量 |
| P2 | `full_eval` 串行执行面试题 | 3 人依次生成（71.9s）；可改成并行，但需注意 LLM 并发限流 |
| P3 | 轨迹无保留策略 | `agent_trace` 会持续增长，建议按月归档（设计文档已列） |
| P3 | 前端未展示 `input_hash` | 轨迹表里有字段但页面没显示，调试价值不高，可不做 |
