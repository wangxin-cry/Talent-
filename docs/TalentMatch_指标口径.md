# TalentMatch 指标口径说明（V1）

> 看板与成本页的每个数字都必须能对上一个明确口径。本文是「答辩/验收时被追问」的答案底稿。
> 实现位置：`backend/app/services/analytics.py`、`backend/app/services/costs.py`。

---

## 一、核心指标

| 指标 | 口径 | 实现 |
|---|---|---|
| 在招职位 | `job.status = published` 的数量 | `count(job where status='published')` |
| 投递总数 | `application` 全表行数（含所有状态、含淘汰） | `count(application)` |
| 待面试 | 当前 `status = interview` 的人数（现状口径） | `count(application where status='interview')` |
| 已入职 | 当前 `status = hired` 的人数 | 同上 |
| 平均招聘周期 | **仅统计已入职样本**：`hired_at - applied_at` 的算术平均（天，保留 1 位） | 无样本时返回 `null`，**不返回 0**（0 会被误读成"当天入职"） |

> 说明：平均周期只在 `hired` 上算，淘汰样本不参与；样本为 0 时前端显示「—」。

---

## 二、漏斗（本阶段修正过口径）

### 2.1 为什么不能用"当前状态人数"

早期实现用「当前停留在各状态的人数」画漏斗，会导致：

- 候选人流转到下一阶段后，上一阶段人数**减少**，漏斗看起来像倒挂；
- 转化率会算出凭空的 100%（如 screening=1、interview=1 → 100%，实际是 1/2）；
- 已入职的人不再计入"面试过"，与业务直觉相反。

### 2.2 现在的口径：**到达过**

```
count    = 到达过该阶段的应聘数（去重 application）
current  = 当前停留在该状态的人数（现状视角，单独给出）
share    = count / 投递总数
conversion = 本阶段 count / 上一阶段 count
```

- 数据来源：`application_stage_history`（每次流转一条 `to_status`），
  用 `distinct application_id` 去重；
- 兜底：若历史缺失，用 `application.status` 补充，避免漏计；
- 该口径天然**单调不增**，与业务漏斗一致。

示例（库里 3 条申请：1 停在 new、1 在 screening、1 在 interview）：

| 阶段 | 到达 | 当前 | 占比 | 转化 |
|---|---:|---:|---:|---:|
| 新申请 | 3 | 1 | 100% | — |
| 筛选中 | 2 | 1 | 67% | 66.7% |
| 面试中 | 1 | 1 | 33% | 50% |
| Offer | 0 | 0 | 0% | 0% |
| 已入职 | 0 | 0 | 0% | 0% |

---

## 三、渠道

| 字段 | 口径 |
|---|---|
| `total` | 该渠道的投递数 |
| `interview` | 该渠道**到达过面试**的人数（含之后转 offer/hired 的人） |
| `hired` | 该渠道**到达过入职**的人数 |
| `rejected` | 该渠道**被淘汰过**的人数 |
| `conversion` | `hired / total`（入职转化率） |

> 渠道字段来自 `application.source`；未填写归入「未标注」。

---

## 四、阶段平均停留

| 字段 | 口径 |
|---|---|
| `samples` | 从该阶段流转出去的样本数 |
| `avg_hours` | `duration_in_prev_status` 的平均值（小时，保留 1 位） |

- 数据来源：`application_stage_history.duration_in_prev_status`（流转时写入的冗余字段）；
- 仍停留在该阶段的申请不计入（还没产生停留时长）。

---

## 五、成本指标

| 指标 | 口径 |
|---|---|
| 调用数 | `ai_call` 行数（**每次真实 LLM 调用一行**） |
| token | `sum(total_tokens)`，其中 `total = input + output` |
| 费用 | `(input/1000)*输入单价 + (output/1000)*输出单价`，按模型精确匹配，未收录走默认单价 |
| 月份口径 | 自然月（服务端 UTC 零点起算），页面上标注「UTC 当日/本月」 |
| 预算使用率 | `本月费用 / MONTHLY_BUDGET_CNY` |
| 预算状态 | `<80% ok`、`80%~100% warning`、`>=100% exceeded`、预算配置为 0 时 `disabled` |
| 缓存命中 | 命中缓存**不产生调用**，因此不写台账；`ai_call.cache_hit` 仅预留给显式记录场景 |

> 金额使用 `DECIMAL(10,6)`，单价表在 `backend/app/core/pricing.py`；调整单价不改写历史记录。

### 一次真实调用校验（实测）

```
模型 deepseek-ai/DeepSeek-V4-Flash
输入 1379 tokens，输出 1212 tokens
费用 = 1379/1000*0.001 + 1212/1000*0.002
     = 0.001379 + 0.002424
     = 0.003803 元   ✅ 与台账一致
```

---

## 六、已知局限（诚实说明）

1. **时区**：月度统计按 UTC 自然月，跨时区对账会有边界差；如需北京时间口径，改 `_month_start` 即可。
2. **"待面试"是现状口径**，与漏斗的"到达过面试"不同，两个数字不相等是正常的。
3. **平均周期样本少时不具统计意义**，看板上保留小数位但不应过度解读。
4. **渠道转化率只有入职转化**，没有"投递→面试"转化率；需要时按 `interview/total` 另算。
