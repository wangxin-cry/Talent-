# TalentMatch 分步实施路线图（V1.0）

> ⚠️ **本文已被取代，仅作历史参考。**
> 当前有效文档：**《TalentMatch_项目设计方案_V1.md》**（架构与分阶段）、**《TalentMatch_数据库设计_V1.md》**（20 张表）、**《TalentMatch_对话式交互与产品画面_V1.md》**（交互与界面）。
> 本文写作时尚未确定「从零开发 + MinIO 对象存储」这两个决定，其中技术栈、存储、建表数量相关结论已过时。

> **先看这份会懵：本文是技术附录（Step/M 编号、PRD 追溯、验收口径）。要照着做，请看同目录《TalentMatch_阶段任务计划.md》——9 个阶段，白话描述"干什么 / 做完看到什么 / 不做什么"。**

> 输入：`TalentMatch_PRD_SRS_V1.0.md`（9 大模块 / 42 项功能 / 6 条 Phase 1 验收 / 5 条通用验收）
> 输出：16 个可执行步骤（S0~S15），每步给出「目标 / 前置 / 任务 / 产出 / 完成标准 / 坑 / PRD 对应」
> 配套：`TalentMatch_任务看板.xlsx`（核心版、总览、任务清单、需求追溯、验收、风险、说明 7 个页签）
> **当前执行口径（2026-11-19 修订）**：按「核心版」推进 —— **M0~M9，6 周 / 30 人日**，只保核心闭环；S10~S15 与 13 项 P1 功能列为「扩展」，做完核心再按需补。范围取舍见 §1.5，压缩节奏见 §3.1。

---

## 0. 这份文档怎么用

1. **先看第 3 章 §3.1 核心线**（M0~M9，6 周 / 30 人日）——这是当前执行计划。§3.2 的 16 步是完整版扩展参考，不要一上来就按它排期。
2. **按 S0→S15 顺序做**。每步都有 DoD（完成标准），DoD 不满足不要进下一步——招聘平台的数据模型是链式的（职位→简历→匹配→流程），前面漏字段，后面全返工。
3. 每一步的「任务」条目编号（`T4.2` 这种）与看板「1.任务清单」一一对应，可直接勾选跟踪。
4. 第 5 章是 42 项需求追溯矩阵，答辩/验收时逐条对；第 6 章是 PRD §14 的验收判据。
5. 第 10 章是「今天就能开始的 10 个动作」。

时间单位：**人日**（1 人全职、5 天/周）。课余开发把总人日 ×1.8~2.2。

---

## 1. 输入与基线

### 1.1 PRD 的关键约束（拆步骤前必须先记住）

| 维度 | 内容 | 对实施的影响 |
|---|---|---|
| 核心闭环 | 发布职位 → 简历解析 → 智能匹配 → 面试辅助 → 流程自动化 → 数据分析 → 优化 | 六块必须能串起来，**串不起来的分模块都是白做** |
| Phase 1 范围 | 6.1~6.9 共 37 项（P0/P1） | 每块先做「最小可用」，再补 P1 |
| Phase 1 排除 | 视频面试、薪酬谈判、入职自动化、人才画像搜索、多语言、私有化部署 | 需求表里遇到这 6 项统一标「不做」，防止范围蔓延 |
| 成功指标 | 解析准确率 ≥90%、匹配准确率 ≥80%、周期缩短 ≥30%、成本降 ≥20% | 决定了必须有：**人工标注集 + 一致率评测**，不能只靠 demo |
| 验收 A1~A6 | 职位全流程、四格式解析、匹配一致率、面试问题、状态流转+通知、看板准确 | 这就是你的答辩提纲，每步产出要能指向其中一条 |
| 非功能 | 首屏 ≤3s、API P50 ≤300ms、100 并发、可用性 ≥99.5% | 前端分页/骨架屏、后端索引/分页、批量走异步 |

### 1.2 42 项需求的 Phase 归属（先背下来）

- **Phase 1（37 项）**：UC-01~06、JM-01~04、RP-01~05、SM-01~04、IA-01~03、RA-01~04、DA-01~05、CE-01~03、CC-01~03。
- **Phase 2（5 项，明确不做）**：JM-05 职位模板、SM-05 人才库推荐、IA-04 面试报告、CE-04 满意度调查、CC-04 成本月报。
- **角色（3 个）**：Recruiter（招聘专员）、Hiring Manager（用人经理）、Admin（管理员）。权限矩阵见 PRD §4.2，S2 一次做完，别拖到最后。

### 1.3 技术栈锁定（本项目内不再改）

```
后端：Python 3.11 / FastAPI / SQLAlchemy 2.0 / Pydantic v2 / Alembic
     开发期 SQLite(WAL) + BackgroundTasks，演示期 PostgreSQL 18 + Celery + Redis
前端：Next.js 14 App Router / TypeScript / Tailwind / shadcn/ui / Recharts
AI：OpenAI 兼容协议（DeepSeek / 通义千问），无 Key 时走内置 Mock provider
文件：抽象 Storage 接口（本地磁盘 / 可选 MinIO）
测试：pytest + httpx.AsyncClient；前端少量 vitest；覆盖率目标核心服务 ≥80%
```

### 1.4 与 PRD 9.1 的 5 处主动偏离（写进 `docs/ADR-001`）

| # | PRD 写的 | 本项目实际 | 理由 |
|---|---|---|---|
| 1 | MinIO 对象存储 | 本地磁盘 + `Storage` 接口（S3 兼容实现留在 Phase 2） | 本机无 Docker/MinIO；不影响业务代码 |
| 2 | 关系库固定 PostgreSQL 16+ | 开发 SQLite、演示 PG18 | 降低「环境没起来就写不了代码」的风险；用 SQLAlchemy 方言隔离 |
| 3 | Celery + Redis | 可切换队列：内存队列（开发）/ Celery（演示） | 本机无 Redis；抽象 `TaskRunner`，业务只调接口 |
| 4 | spaCy / HanLP 中文 NLP | 规则 + 技能词典 + LLM 结构化抽取 | 中文简历字段抽取用 LLM 更稳；NLP 库体积大、Windows 编译坑多 |
| 5 | 6 个微服务 Docker 部署 | Phase 1 单体 FastAPI（模块化包边界）+ 1 个 worker | 微服务对单人项目是纯负担；包边界保证以后可拆 |

### 1.5 核心版范围与取舍（当前执行口径）

> 结论：**不做完整 Phase 1**。核心版 = 19 项必做 + 5 项简版，13 项砍掉，5 项 Phase 2 不碰；总工期从 68 人日压到 **30 人日 / 6 周**。

**A. 必做（19 项，缺一项演示就不完整）**

| 模块 | 需求 | 一句话理由 |
|---|---|---|
| 账号 | UC-01 注册、UC-02 登录 | 没有账号就没有角色，权限演示不了 |
| 职位 | JM-01 创建(AI JD)、JM-02 列表筛选、JM-04 归档 | 闭环的起点 |
| 简历 | RP-01 多格式(PDF/Word/图片降级)、RP-02 提取、RP-03 去重、RP-04 校对、RP-05 批量 | 闭环的燃料，也是最容易出彩的部分 |
| 匹配 | SM-01 技能、SM-02 经验、SM-03 评分排名、SM-04 理由 | 产品的核心价值，答辩必看 |
| 面试 | IA-01 问题生成 | 单位成本最低、感知最强的 AI 功能 |
| 流程 | RA-01 站内通知、RA-03 状态管理 | 让「招聘流程」不是一个静态表格 |
| 数据 | DA-01 看板、DA-03 周期 | 证明数据是真的在流转 |

**B. 简版（5 项，做最小实现，不做完整交互）**

| 需求 | 核心版做到什么程度 |
|---|---|
| UC-06 用户列表 | Admin 只读列表（不删不改角色） |
| JM-03 职位审批 | 发布前一次「确认发布」，不做多级审批人 |
| DA-02 渠道分析 | 一张对比图（简历数/面试数），不做转化率拆解 |
| CC-01 Token 统计 | `ai_calls` 记账 + 后台日志，不做独立页面 |
| CC-03 优化策略 | 模型分级 + 缓存命中，两项实现即可 |

**C. 砍掉（13 项 Phase 1 功能，写进 known issues，不当作 bug）**

| 分组 | 需求 | 为什么现在砍 |
|---|---|---|
| 演示价值低、成本高 | CE-01 投递页、RA-02 面试安排(ICS)、DA-05 报表导出 | 各要 1~2 天，演示 10 秒就过 |
| 依赖外部通道/定时器 | RA-04 SLA 监控、CC-02 成本预算、CE-03 邮件自动反馈 | 没邮件服务、没定时任务，做了也只能假跑 |
| 上线才需要 | UC-03 密码重置、UC-04 个人信息、UC-05 API Key、IA-02 评估模板、IA-03 面试记录、DA-04 成本分析、CE-02 进度查询 | 内部演示用不到，答辩也不会问 |

**D. 三条不能砍的底线**（砍功能可以，砍这三条会直接翻车）

1. 密码 bcrypt 哈希 + JWT 双 token（access/refresh），`SECRET_KEY` 走 `.env`。
2. 候选人手机号/邮箱加密存储 + 列表脱敏（`138****1234`）。
3. 每个接口都有 `require_role` + 归属校验（别人的候选人返回 404）。

**E. 为扩展留的结构**（以后补 S10~S15 不用重构）

- 表结构一次建齐 13 张（哪怕核心只用 9 张），S10 记账、S8 通知、S12 审计都能直接落。
- 状态机、`stage_history`、`source` 字段从第一天就有，DA-02/DA-03 后面只加查询。
- 评测脚本（解析/匹配）从 S4/S5 就写，KPI 数字随时能重算。

---

## 2. 本机现状与缺口

### 2.1 环境矩阵（实测，2026-11-19）

| 组件 | 现状 | 结论 |
|---|---|---|
| Python | conda env `py311` = 3.11.15，已装 fastapi 0.141.1 / sqlalchemy 2.0.51 / pydantic 2.13.4 / pydantic-settings / uvicorn 0.52.1 / httpx | **直接用这个 env**，缺的包 pip 补 |
| Python(导出) | 内置 3.12.14 带 openpyxl / pandas / python-docx | 做报表导出与 xlsx 生成 |
| Node | v22.21.1，npm 10.9.4 | 够跑 Next 14；`npm.ps1` 被策略拦，必须用 **`npm.cmd`** |
| Git | 2.51.0 | 可用 |
| PostgreSQL | 服务 `postgresql-x64-18` 已安装，**Stopped**，PATH 里无 psql | S1 先确定端口/密码/启动方式 |
| Redis | 未安装 | 开发期不上 Redis；演示前装 Memurai 或用 WSL |
| Docker | 未安装 | S14 容器化交付改为「文档 + compose 文件」，本机用进程方式跑 |
| MySQL | 服务运行中 | 本项目不用，别被它带偏 |
| LLM Key | 未确认 | S0 第一件事确认；没有就全程 Mock |

### 2.2 缺口清单（真正的开工量）

| # | 缺口 | 严重度 | 影响 | 在哪步补 |
|---|---|---|---|---|
| G1 | 无工程骨架、无数据模型 | P0 | 一切无从开始 | S1 |
| G2 | 无认证/RBAC | P0 | 验收 A1 卡死，多角色无法演示 | S2 |
| G3 | 无解析链路（PDF/Word/图片） | P0 | 验收 A2 卡死 | S4 |
| G4 | 无技能词典与匹配算法 | P0 | 验收 A3 卡死（PRD 只给了功能，没给算法） | S5 |
| G5 | 无标注集与一致率评测 | P0 | 三个 KPI 无法证明 | S0 建集，S5/S6 跑评测 |
| G6 | 无异步任务与进度反馈 | P1 | 批量 100 份必超时 | S4 |
| G7 | 无通知/邮件通道 | P1 | 验收 A5 卡死 | S8 |
| G8 | 无状态机约束 | P1 | 候选人状态乱跳，数据不可信 | S6 |
| G9 | 无 Token 计费与预算 | P1 | CC-01~03 缺失，成本不可控 | S10 |
| G10 | 无审计/脱敏/限流 | P1 | §10 合规项答辩被问倒 | S12 |
| G11 | 无测试、无覆盖率 | P1 | §8.5 明确 ≥80% | 每步补，S13 收口 |
| G12 | 无部署脚本与文档 | P1 | 验收 G5 卡死 | S14 |

### 2.3 这个项目最容易踩的 12 个坑（提前写进开发手册）

1. **Windows 执行策略**：`npm`/`npm.ps1` 被拦 → 全部用 `npm.cmd`；Python 不在 PATH → 用 conda env 绝对路径。
2. **中文路径与空格**：PRD 与项目路径含中文很正常，但上传目录一律用 `UUID` 命名，日志/文件名统一 UTF-8，禁止把候选人姓名拼进路径。
3. **SQLite 方言差异**：JSONB→`JSON`、ENUM→`String + CheckConstraint`、`UUID`→`CHAR(36)`。切 PG 时只改 `config.DATABASE_URL`，模型层不许出现方言函数。
4. **SQLite 并发写**：必须开 WAL，且后台任务写库要串行（单 worker 或用队列），否则 `database is locked`。
5. **PDF 中文乱码**：大量中文简历是 CID 字体，`pdfplumber` 抽出来是乱码 → 必须有降级链（pdfplumber → PyMuPDF → OCR/视觉 LLM → 人工校对）。
6. **LLM 返回非严格 JSON**：会包 ```json 围栏、会多写解释、会缺字段 → `ai/client.py` 统一做「解析→修复→重试→字段级兜底」，任何一层失败都不能整条丢弃。
7. **匹配分数不可解释**：只存一个 0.83 的分数，验收 A3 无法答辩 → 必须落 `matched_skills / missing_skills / 经验差 / 理由` 明细。
8. **批量上传阻塞**：100 份简历同步解析必定超时 → 上传只落库+入队，解析在后台，前端轮询进度。
9. **去重误合并**：同名同姓很常见，绝不能只按姓名去重 → 强键 email/phone，弱键「姓名+手机后4位+公司」组合。
10. **状态机乱跳**：前端直接改 status 是事故源头 → 全部走 `POST /applications/{id}/transition`，服务端校验允许的边。
11. **隐私泄漏在日志里**：`logger.info(resume_text)` 直接把候选人信息写进日志 → 统一日志脱敏（手机/邮箱/姓名打码）。
12. **成本失控**：每次打开职位页都重算匹配 → 匹配结果落库 + 输入指纹（简历内容 hash + JD 版本）做缓存，LLM 只做理由与仲裁。

---

## 3. 总体路线

### 3.1 核心线（当前执行）：M0~M9，6 周 / 30 人日

| M | 对应 Step | 内容 | 人日 | 周末必须能演示 | 相比完整版砍掉 |
|:--:|:--:|---|:--:|---|---|
| M0 | S0(简) | 需求基线(24 项)、环境固化、解析+抽取 2 个 spike、标注集 20 条 | 2 | 能一句话说清做什么/不做什么 | 另外 4 个 spike、成本估算 |
| M1 | S1(简) | 9 张表 + 迁移 + 前端脚手架 + `/healthz` | 3 | 前端首页能调通健康检查 | 队列抽象、Celery、启动脚本 |
| M2 | S2(简) | 注册/登录/JWT/三角色种子/路由守卫 | 2.5 | 三个角色分别登录，菜单不同 | 重置、API Key、用户管理、审计 |
| M3 | S3 | 职位 CRUD/发布/AI 生成 JD/技能词典 | 3 | 现场建一个职位并发布 | 多级审批（简化为确认发布） |
| M4 | S4 | 上传/解析(PDF/Word/图片降级)/抽取/去重/校对/批量 | 5 | 一次传 10 份，出结构化结果 | 100 份压测、失败重试队列 |
| M5 | S5 | 特征/评分/理由/排名/评测 | 5 | 一键匹配出排名 + 点开理由 | 权重多组对比、反馈学习 |
| M6 | S6+S8(简) | 候选人/状态机/流程视图 + 站内通知 | 3 | 把候选人从 new 推到 interview 并收到通知 | 邮件、ICS、SLA、公开投递页 |
| M7 | S7(简) | 面试问题生成 + 展示 | 2 | 为排名第 1 的候选人生成 8 个问题 | 评估模板、面试记录 |
| M8 | S9(简) | 漏斗/周期/渠道简版看板 | 3 | 看板数字与手算一致 | 报表导出、成本分析 |
| M9 | — | seed 数据/联调/演示脚本/README/验收简表 | 2.5 | 5 分钟演示一遍不卡壳 | 三份正式文档、容器化 |

**合计 30~31 人日**，全职 6 周（5 天/周），课余按 ×2 算约 12 周。

**如果只剩 3 周**：取 M0~M5 + M9 简版（约 22 人日）＝「闭环演示版」，M6~M8 后补。**先保住能演示的闭环，任何情况下不要为了做全而做不完。**

### 3.2 完整版 16 步总览（扩展参考，核心版只取子集）

> 下表的 S0~S15 是「完整 Phase 1」的拆分。核心版按 §3.1 取 `S0~S9` 的精简子集，`S10~S15` 全部延后；做完核心后想补，按原步骤回来做即可，目录与表结构不用重构。

| Step | 名称 | 主要产出 | 人日 | 依赖 | 里程碑 | PRD |
|:--:|---|---|:--:|:--:|:--:|---|
| 0 | 需求冻结与技术预研 | 需求基线、标注集 v1、6 个 spike 结论 | 3 | — | — | 全部 |
| 1 | 工程骨架 + 数据模型 | 13 张表、迁移、/healthz、前端脚手架 | 4 | 0 | — | §7/§9 |
| 2 | 用户中心与鉴权 | 注册/登录/刷新/登出/重置/API Key/RBAC | 5 | 1 | M1.1 | UC-01~06 |
| 3 | 职位管理 | JD CRUD/AI 生成 JD/发布审批/归档 | 4 | 2 | M1.2 | JM-01~04 |
| 4 | 简历上传与智能解析 | 四格式解析、异步批量、去重、校对 | 6 | 3 | M1.3 | RP-01~05 |
| 5 | 智能人岗匹配 | 技能/经验/综合评分、排名、匹配理由 | 6 | 4 | M1.4 | SM-01~04 |
| 6 | 候选人库与应聘流程 | 候选人档案、状态机、SLA 字段 | 3 | 5 | — | RA-03 |
| 7 | AI 面试辅助 | 问题生成、评估模板、面试记录 | 3 | 5 | M1.5 | IA-01~03 |
| 8 | 流程自动化与候选人体验 | 通知、面试安排(ICS)、SLA 监控、投递页、进度查询 | 5 | 6 | M1.6 | RA-01/02/04、CE-01~03 |
| 9 | 招聘数据分析 | 漏斗/KPI/渠道/周期/成本看板 + 导出 | 5 | 6 | M1.7 | DA-01~05 |
| 10 | AI 成本控制 | ai_calls 计量、预算告警、模型分级、缓存 | 4 | 5 | — | CC-01~03 |
| 11 | 前端整体打磨 | 信息架构、设计系统、空/错/载状态、响应式 | 5 | 3~10 | — | §8.1、G1/G3 |
| 12 | 安全与合规加固 | 限流、AES 加密、脱敏、审计、OWASP 自查 | 4 | 2~10 | — | §10、G4 |
| 13 | 测试与质量 | 单测/接口测试/覆盖率 ≥80%、评测集回归 | 4 | 全部 | — | §8.5 |
| 14 | 部署与交付 | compose、启动脚本、API/用户/部署文档 | 4 | 全部 | — | §9.3、G5 |
| 15 | 验收与演示 | A1~A6 证据、KPI 实测、演示脚本 | 3 | 全部 | — | §14 |

合计 **68 人日**（扩展完整版：A 线 30 / B 线 52 / C 线 68）。

### 3.3 可并行点（有队友时）

- 后端主线 `S1→S2→S3→S4→S5→S6` 必须串行（数据模型是链式依赖）。
- **S7 面试辅助** 依赖 S5 的匹配明细，可与 S6 并行（同一个人做也就差 1 天）。
- **S9 看板** 依赖 S6 的状态数据，但**图表组件可以在 S3 之后先搭**，接口定稿后再接。
- **S10 成本** 与 **S12 安全** 互不依赖，可并行。
- **S11 前端打磨** 与 **S13 测试** 可两人并行（一个改样式，一个补断言）。

### 3.4 与 PRD §11 里程碑的对照

| PRD 里程碑 | 工期(PRD) | 本项目 Step | 备注 |
|---|---|---|---|
| M1.1 用户系统 | 第1-2周 | S1+S2 | 骨架和鉴权一起交 |
| M1.2 职位管理 | 第2-4周 | S3 | 含 AI 生成 JD |
| M1.3 简历解析 | 第4-6周 | S4 | 四格式 + 批量 |
| M1.4 匹配引擎 | 第6-8周 | S5 | 含标注集评测 |
| M1.5 面试辅助 | 第8-9周 | S7 | 问题生成 + 记录 |
| M1.6 流程自动化 | 第9-11周 | S6+S8 | 状态机先行 |
| M1.7 数据分析 | 第11-12周 | S9 | 漏斗 + 渠道 + 周期 |
| （PRD 未列） | — | S0/S10~S15 | 预研、成本、前端、安全、测试、交付、验收 |

---

## 4. 分步详解

> 统一结构：**目标 → 前置 → 任务 → 产出 → 完成标准(DoD) → 坑 → PRD**。
> 任务编号 `T<Step>.<n>` 与 `TalentMatch_任务看板.xlsx` 的「1.任务清单」一致。

### Step 0 — 需求冻结与技术预研（3 人日）【核心·M0，精简为 2 天】

**目标**：把 42 项需求变成可勾选清单；把 6 个「可能让项目卡死」的技术点先验证掉；建好标注集（否则 S5 无法证明准确率）。

**前置**：拿到 PRD；确认 LLM API Key 有无；确认 PG18 能否启动。

**任务**

- T0.1 抽需求基线：把 42 个编号（UC/JM/RP/SM/IA/RA/DA/CE/CC）抄成表，每条标 `优先级 / Phase / 验收方式 / 实现步骤`，存 `docs/需求基线.md`。
- T0.2 写 `docs/ADR-001-技术栈与边界.md`：锁定 §1.3 的技术栈，写清 §1.4 的 5 处偏离，以及「Phase 1 不做什么」。
- T0.3 环境固化：确认 conda `py311` 可用、`npm.cmd` 可用、PG18 启动方式；产出 `docs/环境清单.md`（每条命令 + 版本号）。
- T0.4 Spike A（解析）：准备 6 份真实中文简历（PDF 表格/PDF 双栏/扫描图/Word/图片/超长），跑 `pdfplumber`+`python-docx`+`PyMuPDF`，统计「能抽出多少有效字段」，结论写 `docs/spike-A-解析.md`。
- T0.5 Spike B（LLM 结构化）：用同一批简历跑 20 次「简历→JSON」抽取，统计 JSON 合法率 / 必填字段完整率 / 姓名电话准确率，写 `docs/spike-B-抽取.md`。
- T0.6 Spike C（匹配一致性）：人工给 30 份简历 × 1 个职位打「合适/一般/不合适」标签，写清标注口径（技能硬门槛怎么算），产出 `docs/标注集-v1.csv` + `docs/标注口径.md`。
- T0.7 Spike D（队列）：确认「BackgroundTasks 能否支撑 100 份批量解析」；同时确认 Celery 是否可装（无 Redis 时先只做接口抽象），写 `docs/spike-D-队列.md`。
- T0.8 Spike E（LLM 成本）：跑一次完整「解析+匹配+理由」，记录 token 与耗时，估算 1000 份简历的月成本，写 `docs/spike-E-成本.md`。

**产出**：`docs/需求基线.md`、`docs/ADR-001*.md`、`docs/spike-A~E*.md`、`docs/标注集-v1.csv`、`docs/环境清单.md`。

**DoD**：42 行需求表齐全；6 个 spike 都有「结论 + 数字 + 证据」；标注集 ≥30 条且口径写清；能用一句话说清「Phase 1 我不做什么」。

**坑**：不要在这一步写业务代码；标注集质量决定后面所有准确率数字，宁可少（30 条）但要准。

**PRD**：全量（尤其 §3.2 边界、§11 里程碑、§14 验收）。

---

### Step 1 — 工程骨架 + 数据模型（4 人日）【核心·M1，精简为 3 天】

**目标**：一条命令起服务，一个 URL 看到 13 张表建成，前端脚手架能打开。

**前置**：S0 完成，`docs/需求基线.md` 在手。

**任务**

- T1.1 建目录（见第 8 章）：`backend/`、`frontend/`、`docs/`、`scripts/`、`samples/`（样例简历）。
- T1.2 `backend/requirements.txt` 锁版本：fastapi、uvicorn、sqlalchemy[asyncio]、aiosqlite、asyncpg、alembic、pydantic-settings、python-jose[cryptography]、passlib[bcrypt]、bcrypt==4.0.1、python-multipart、httpx、openai、pdfplumber、PyMuPDF、python-docx、openpyxl、Pillow、pytest、pytest-asyncio、slowapi、cryptography。**一次装完，别分步装**。
- T1.3 `core/config.py`：全部配置走 `.env`（DATABASE_URL / LLM_BASE_URL / LLM_API_KEY / LLM_MODEL / SECRET_KEY / STORAGE_DIR / QUEUE_MODE / BUDGET_CNY / 限流阈值），同步产出 `.env.example`。
- T1.4 `core/database.py`：async engine + session 工厂；SQLite 开 WAL、`pool_pre_ping`；PG 用 asyncpg 且 `statement_cache_size=0`。
- T1.5 `models/models.py`：13 张表 + 索引 —— `companies / users / api_keys / jobs / candidates / resumes / resume_files / applications / match_results / interviews / interview_feedback / notifications / ai_calls / audit_logs`。字段对齐 PRD §7.2，另补：`applications.source`（渠道，DA-02 要用）、`applications.stage_entered_at`（周期分析要用）、`jobs.jd_version`（匹配缓存键）、`match_results.detail_json`（可解释性）。
- T1.6 `alembic init` + 第一版迁移；后续所有改表走迁移（`create_all` 只用于测试）。
- T1.7 `main.py`：lifespan、CORS、统一异常处理器（业务错误码 `{code,message,detail}`）、`/healthz`（DB + 存储 + 队列）。
- T1.8 `core/deps.py`：`get_db / get_current_user / require_role(...)` 三个依赖先留桩，S2 填实现。
- T1.9 前端脚手架：`npm.cmd create next-app`（TS + Tailwind + App Router）+ shadcn 初始化，跑通空白首页与 `/api/health` 代理。
- T1.10 `scripts/dev.ps1`：一条命令起后端（uvicorn）+ 前端（next dev）；`scripts/migrate.ps1` 跑迁移。

**产出**：可启动的后后端骨架、13 张表、首个迁移、前端脚手架、两条启动脚本。

**DoD**：`/healthz` 返回 `{"db":"ok","storage":"ok","queue":"memory"}`；`alembic upgrade head` 成功；`/docs` 能打开；前端首页能调通 `/healthz`；`models.py` 里每张表都有注释。

**坑**：SQLite 与 PG 的类型差异必须在模型层处理干净（见坑 3）；`passlib 1.7.4 + bcrypt 5.x` 会报 `__about__`，锁 bcrypt 4.0.1；Alembic 自动生成对 SQLite 支持一般，首版手写更稳。

**PRD**：§7 数据模型、§9.1 选型、§9.3 部署（开发态简化）。

---

### Step 2 — 用户中心与鉴权（5 人日）【核心·M2，精简为 2.5 天】

**目标**：注册→登录→刷新→登出→重置密码→API Key 全通，三角色权限真正生效。

**前置**：S1。

**任务**

- T2.1 `schemas/user.py`：注册（密码强度：≥8 位、字母/数字/特殊字符至少两类）、登录、Token 对、UserResponse（api_key 掩码：前后各 4 位）、角色枚举。
- T2.2 `core/security.py`：bcrypt 哈希、access 30min + refresh 7d、jti 黑名单（内存/SQLite 表，Redis 可选）、`mask_secret()`、`encrypt_pii()/decrypt_pii()`（Fernet，给 S12 用）。
- T2.3 `api/v1/auth.py`：`register / login / refresh / logout / me / change-password / reset-request / reset-confirm / api-key(create/list/revoke)`。
- T2.4 登录失败 5 次锁定 15 分钟：计数落 `login_attempts`（或 Redis），命中返回 429 并写审计。
- T2.5 RBAC：`require_role("admin")` 等依赖 + 权限矩阵落 `core/permissions.py`；Admin 才能进用户管理/系统配置/成本/审计。
- T2.6 用户管理接口（UC-06）：列表/禁用/删除/改角色，仅 Admin。
- T2.7 审计日志：注册、登录成功/失败、登出、重置密码、改角色、删除用户各写一条 `audit_logs`。
- T2.8 前端 `/login`、`/register`、`/reset` 三页 + 路由守卫（未登录跳登录）+ 角色菜单隐藏。
- T2.9 `tests/test_auth.py`：6 个用例（重复注册、弱密码、错密码、锁定、刷新、登出后旧 token 失效）。

**实现状态（2026-11-20，精简版已交付）**

| 任务 | 状态 | 实际落地 |
|:--:|:--:|---|
| T2.1 | ✅ | `schemas/auth.py`；密码 8~64 位且字母+数字（未强制特殊字符） |
| T2.2 | ✅ | bcrypt、access 30min + refresh 7d；用 `user.token_version` 代替 jti 黑名单，无需额外表 |
| T2.3 | ⚠️ | 已完成 register / login / refresh / logout / me / reset-request / reset-confirm，另加 verify-email / resend-verification；**change-password、api-key 未做** |
| T2.4 | ✅ | 落 `user.login_fail_count` / `locked_until`，5 次锁 15 分钟；**命中返回 403 而非 429** |
| T2.5 | ✅ | `require_roles` 基于数据库角色判断；未单独建 `core/permissions.py`，常量集中在 `models/user.py` |
| T2.6 | ⚠️ | 仅 `GET /api/v1/admin/users`；禁用/删除/改角色未做 |
| T2.7 | ❌ | `audit_log` 未建，暂未写审计 |
| T2.8 | ✅ | 5 个页面（登录/注册/验证/忘记/重置）+ 守卫 + 按角色菜单 |
| T2.9 | ✅ | 17 个用例，覆盖 6 项并补充 RBAC 越权、角色即时生效、登出后 refresh 失效 |

**产出**：完整账号体系、9 个鉴权接口、5 个页面、RBAC 依赖、17 个测试。

**DoD**：用例全绿；登出后旧 access 立即 401；第 5 次错密码 403 且 15 分钟内正确密码也拒；非 Admin 调 `/admin/users` 返回 403；api_key 功能顺延至后续阶段。

**坑**：JWT 的 `sub` 必须是字符串（UUID 要 `str()`）；SECRET_KEY 不许硬编码；刷新 token 轮换时要同步失效旧的 jti，否则「登出」形同虚设。

**PRD**：UC-01~06、§6.1.3、§4.2 权限矩阵、§8.3 认证。

---

### Step 3 — 职位管理（4 人日）【核心·M3】

**目标**：JD 能建、能 AI 补全、能走审批、能发布/归档，列表能搜能筛。

**前置**：S2。

**任务**

- T3.1 `schemas/job.py`：创建/更新/列表/详情；字段 `title/description/requirements/skills(list)/department/location/headcount/salary_range/status`；状态枚举 `draft/pending/published/closed/archived`。
- T3.2 `api/v1/jobs.py`：CRUD + `POST /jobs/{id}/submit`（提审）+ `POST /jobs/{id}/approve|reject`（Hiring Manager）+ `POST /jobs/{id}/publish|close|archive` + `GET /jobs?keyword=&status=&department=`。
- T3.3 状态机：`draft→pending→published→closed→archived`，非法跳转 400 并说明允许的边；发布时校验「requirements 非空、skills ≥1」。
- T3.4 AI 生成 JD：`services/jd_writer.py`，输入「职位名称 + 部门 + 3 个关键词」→ 输出 description/requirements/skills 三段（严格 JSON），前端一键填入并允许人工改。
- T3.5 技能归一化：`services/skill_dict.py` 建 200+ 条技能词典（含同义词：K8s→Kubernetes、JS→JavaScript、前后端常见栈），JD 的 skills 存储为规范化后的标准名。
- T3.6 前端职位页：列表（卡片/表格切换）+ 筛选 + 新建抽屉（含 AI 生成按钮）+ 详情 + 审批按钮（按角色显示）。
- T3.7 `tests/test_jobs.py`：状态机非法跳转 400、非 Hiring Manager 审批 403、发布缺 requirements 422。

**产出**：职位全流程 API、AI JD 生成、技能词典 v1、职位管理页、3 个测试。

**DoD**：验收 A1 的「创建/编辑/发布/归档全流程」可用；AI 生成 JD 成功率 ≥90%（10 次里 9 次三段齐全）；技能归一化对 20 个常见写法都能映射到标准名。

**坑**：AI 生成的 JD 必须允许人工编辑再保存，否则面试官不认；`skills` 别存自由文本，不然后面匹配全乱。

**PRD**：JM-01~04、§6.2。

---

### Step 4 — 简历上传与智能解析（6 人日）【核心·M4】

**目标**：一次传 100 份，混合 PDF/Word/图片，后台解析出结构化字段，可校对、可去重。

**前置**：S3（候选人/职位已能建）。

**任务**

- T4.1 `services/storage.py`：`save(file)->key` / `open(key)` / `delete(key)`，本地磁盘实现，目录 `data/uploads/{yyyy}/{mm}/{uuid}.{ext}`；大小/类型白名单（pdf/doc/docx/jpg/png，≤20MB）。
- T4.2 `services/parser.py`：格式探测 + 文本抽取链 —— PDF：`pdfplumber` → 失败降级 `PyMuPDF`；Word：`python-docx`（.doc 走 `antiword` 或提示转存）；图片：OCR（PaddleOCR 可选）→ 再降级「视觉 LLM 直读」。统一返回 `{text, pages, method, confidence}`。
- T4.3 `ai/extractor.py`：严格 JSON schema 的简历抽取（姓名/手机/邮箱/城市/学历/学校/专业/工作时间线/公司/职位/技能/项目/证书/期望薪资），含「解析→修 JSON→重试 1 次→字段兜底」四层容错，返回 `field_confidence`。
- T4.4 `services/normalize.py`：手机号（+86/空格/横线）、邮箱小写、日期统一 `YYYY-MM`、公司名去后缀、技能走 T3.5 词典、学历映射（本科/硕士/博士/大专）。
- T4.5 `services/dedupe.py`：强键 `email` / `phone`；弱键「姓名 + 手机后4位 + 最近公司」；命中则合并 resume 并记录 `merged_from`，禁止仅按姓名合并。
- T4.6 批量上传接口：`POST /resumes/batch`（多文件）→ 落 `resume_files` + 建 `parse_tasks` → `TaskRunner.enqueue(parse_resume, id)`；返回批次 id；`GET /resumes/batch/{id}` 给进度（总/成功/失败/进行中）。
- T4.7 `workers/tasks.py`：`parse_resume(file_id)` 单份处理，幂等（按 file hash 去重），失败写 `error_reason` 并可重试；`QUEUE_MODE=memory` 用线程池，`celery` 用 `.delay()`。
- T4.8 校对接口 + 前端：`PATCH /resumes/{id}` 改字段并标记 `manually_edited`；前端上传页（拖拽 + 进度条 + 失败重试）、解析结果页（左原文/右表单，字段高亮低置信度）。
- T4.9 `tests/test_parser.py`：6 份样例各跑一遍，断言「姓名/手机/邮箱/最近公司」四字段抽取正确；乱码样例必须有降级路径且不抛异常。

**产出**：上传/解析/去重/校对全链路、批量进度、样例集回归、解析页。

**DoD**：验收 A2 的「四格式都能解析」；6 份样例四字段准确率 ≥ 90%（人工比对表留档）；100 份批量不阻塞请求（上传接口 <1s 返回）；同一个人传 2 份简历只留 1 条候选人。

**坑**：扫描件不要硬上 OCR（装 PaddleOCR 很重），先用视觉 LLM 兜底并把成本记进 `ai_calls`；解析失败要有 `error_reason` 给 HR 看，不能只留一个 500；**去重必须在入库前做**，否则后面匹配会重复推荐。

**PRD**：RP-01~05、§12 挑战「简历解析准确率」、§8.1 解析速度。

---

### Step 5 — 智能人岗匹配（6 人日）【核心·M5】

**目标**：一个职位一键匹配全库，输出可解释的分数与排名，且与人工标注的一致率达到 80%。

**前置**：S4（有结构化简历）；S0 的标注集。

**任务**

- T5.1 `services/match_features.py`：把简历与 JD 变成可比特征 —— 必须技能命中/缺失、加分技能命中、总年限、相关年限、学历、行业/职级、地点。
- T5.2 `services/scorer.py`：评分公式（可配置权重）`score = 0.50*skill + 0.30*experience + 0.12*education + 0.08*other`；`skill` 用 must-have 覆盖率（缺 must-have 直接乘 0.6 惩罚）+ nice-to-have 加权；`experience` 按「年限差 + 相关度」分段给分。**先算规则分，LLM 不参与打分**。
- T5.3 `services/explain.py`：基于特征生成匹配理由（模板 + LLM 润色二选一）；输出 `summary / matched_skills / missing_skills / risks / suggestion` 五段；LLM 失败降级纯模板。
- T5.4 `services/rank.py`：批量评分（读全部候选人 → 计算 → 落 `match_results`），按 `job_id + resume_hash` 缓存，重复请求命中缓存直接返回。
- T5.5 `api/v1/matching.py`：`POST /jobs/{id}/match`（异步，返回 task）/ `GET /jobs/{id}/matches?min_score=&sort=` / `GET /matches/{id}`（含明细）/ `POST /matches/{id}/feedback`（HR 标注「合适/不合适」，喂后续校准）。
- T5.6 评测脚本 `scripts/eval_match.py`：对标注集 30 条算「三分类一致率 / Top-10 重合率 / Spearman」，输出 `docs/评测-匹配-v1.md`。
- T5.7 前端匹配页：职位侧栏 + 候选人排名表（分数/命中技能/缺失技能/理由展开）+ 排序筛选 + 「不合适」反馈按钮。
- T5.8 `tests/test_match.py`：构造 5 份简历 × 1 JD 的期望分档（高/中/低），断言排序正确；缺 must-have 的简历分数必须低于同经验的全命中简历。

**产出**：匹配引擎、可解释明细、评测报告、匹配页、5 个测试。

**DoD**：验收 A3 的「与 HR 评估一致性 ≥80%」（用 T5.6 的数字说话）；100 份简历匹配 ≤5s（规则分）；同一职位重复打开走缓存不重复计费。

**坑**：这一步最容易「分数看起来合理但没法解释」——明细字段必须落库；权重不要拍脑袋，用标注集调（至少试 3 组权重）；LLM 只做理由，别让它打分（不稳定且贵）。

**PRD**：SM-01~04、§6.4、§12「匹配算法准确性」。

---

### Step 6 — 候选人库与应聘流程（3 人日）【核心·M6】

**目标**：候选人档案可查可搜，应聘状态只能在允许的边上流转，为看板和自动化提供干净数据。

**前置**：S5。

**任务**

- T6.1 `schemas/candidate.py / application.py`：候选人档案（基本信息 + 简历列表 + 标签）、应聘记录（job/candidate/score/status/source/stage_entered_at）。
- T6.2 状态机 `services/pipeline.py`：`new→screening→interview→offer→hired`，任意非终态→`rejected`（必须带 `reject_reason`）；定义 `TRANSITIONS` 表 + `can_transition()`。
- T6.3 `api/v1/applications.py`：创建应聘、`POST /{id}/transition`（校验边 + 写 `stage_history` + 触发通知钩子）、列表（按职位/状态/来源筛选）、批量转移。
- T6.4 候选人库接口：`GET /candidates?keyword=&skill=&status=`，支持按技能标签检索（JSON 字段 + 内存过滤，PG 下可上 GIN）。
- T6.5 前端：候选人列表 + 档案详情（简历预览 + 匹配明细 + 状态时间线）+ 看板式流程视图（按状态分列，拖拽改状态走接口）。
- T6.6 `tests/test_pipeline.py`：非法跳转（new→offer）400；rejected 必填原因 422；合法链全通；每次流转写 history。

**产出**：候选人库、应聘流程、状态机约束、流程看板。

**DoD**：6 条合法链全部可走；5 条非法跳转全部 400；每次流转 `stage_history` 有记录且带操作人；按技能搜「Python」能命中。

**坑**：状态别用前端传的字符串直接写库；`rejected` 是不可逆终态，别允许「反悔」除非 Admin 走特殊接口；`stage_entered_at` 不更新的话 S9 的周期分析全是错的。

**PRD**：RA-03、§6.6、§7.2.3。

---

### Step 7 — AI 面试辅助（3 人日）【核心·M7，精简为 2 天】

**目标**：选中「职位 + 候选人」一键生成 6~8 个个性化面试问题，面试官能记录评分。

**前置**：S5（匹配明细能给出「缺什么」）。

**任务**

- T7.1 `services/interview_gen.py`：输入 JD + 简历 + 匹配缺口 → 输出结构化问题集（`category: 技术深挖/项目追问/行为/情景`、`question`、`looking_for` 考察点、`reference` 参考要点、`follow_up` 追问）；严格 JSON + 失败重试 + 模板兜底。
- T7.2 评估模板：`interview_templates`（维度：技术深度/沟通/主动性/文化匹配，权重可配；1~5 分锚点描述），内置 1 套默认模板。
- T7.3 `api/v1/interviews.py`：`POST /interviews/generate`（缓存键 job+candidate+resume_hash）、`GET /interviews?application_id=`、`POST /interviews/{id}/feedback`（各维度分 + 结论 + 备注）。
- T7.4 前端：面试准备页（问题卡片可勾选、可编辑、可复制）、面试记录表单、反馈汇总。
- T7.5 `tests/test_interview.py`：生成结果 schema 合法率；同输入二次调用命中缓存；反馈分数越界 422。

**产出**：问题生成、评估模板、面试记录、面试页。

**DoD**：验收 A4「基于 JD 和简历生成个性化问题」；生成的问题里 ≥70% 能对应到候选人的具体经历或缺失技能（人工抽检 10 个职位）；缓存命中后响应 <200ms。

**坑**：问题不能是通用八股（「请自我介绍」）——prompt 里强制「每个问题必须引用简历中的具体项目或缺失技能」；生成的 JSON 结构变了会导致前端崩，schema 要锁死。

**PRD**：IA-01~03、§6.5。

---

### Step 8 — 流程自动化与候选人体验（5 人日）【部分核心：只保留站内通知，并入 M6】

**目标**：状态一变就通知；面试能发日历邀请；SLA 超时能告警；候选人能查进度、能自助投递。

**前置**：S6（状态机）、S7（面试）。

**任务**

- T8.1 `services/notify.py`：通知渠道抽象（`console` 默认 / `smtp` / `webhook`），模板表（`resume_received / interview_invite / interview_reminder / offer / rejection / status_update`），渲染占位符；所有发送落 `notifications`（含渠道、模板、状态、错误）。
- T8.2 事件钩子：状态流转时按「目标状态 → 模板」映射自动入队发送（发信失败不影响流转，只记失败可重发）。
- T8.3 面试安排：`POST /interviews/{id}/schedule`（时间、时长、面试官、地点/链接）→ 生成 `.ics` 附件随邀请邮件发出；冲突检测（同面试官同时间段）。
- T8.4 SLA 监控：`services/sla.py` 定义各状态最大停留（如 screening 48h / interview 72h / offer 24h）；定时扫描（启动时 + 每 10 分钟）+ 超时写 `notifications` 并标记 `sla_breached`；Admin 看板可见。
- T8.5 候选人自助投递页（CE-01）：`/careers/{company_slug}` 公开页，展示在招职位 + 上传简历（匿名可投），提交后建 candidate + application 并给确认通知。
- T8.6 进度查询（CE-02）：候选人用「邮箱 + 投递编号」查状态（**只返回状态与下一步，不返回内部评分**），接口限流。
- T8.7 前端：通知中心（列表 + 失败重发）、面试安排弹窗、投递页、进度查询页。
- T8.8 `tests/test_notify.py`：流转触发正确模板；SMTP 失败不影响接口 200；SLA 扫描能标记超时；投递页匿名提交成功。

**产出**：通知中心、ICS 邀请、SLA 告警、公开投递页、进度查询。

**DoD**：验收 A5「状态流转 + 自动通知正常」；4 条主流程（新申请/邀面/offer/拒绝）各能收到正确模板；投递页无需登录可用；进度查询不泄漏分数/内部备注。

**坑**：别用真实 SMTP 做测试（会发垃圾邮件）→ 测试走 console 渠道；`.ics` 时区要写 `Asia/Shanghai` 且带 `TZID`；SLA 扫描别在请求线程里做。

**PRD**：RA-01/02/04、CE-01~03、§6.6、§6.8。

---

### Step 9 — 招聘数据分析（5 人日）【核心·M8，精简为 3 天】

**目标**：一屏看清招聘漏斗、周期、渠道、成本，并能导出 Excel。

**前置**：S6（状态数据）、S8（渠道来源）、S10 可后接（成本口径先留空）。

**任务**

- T9.1 `services/analytics.py`：口径先定死并写 `docs/指标口径.md` —— 漏斗（各状态人数）、转化率（stage→stage）、招聘周期（`applied_at`→`hired_at` 的中位数，按职位/部门/渠道拆）、渠道效果（简历数/面试数/offer 数/单 offer 成本）、SLA 达成率。
- T9.2 `api/v1/analytics.py`：`/dashboard`（核心 KPI 卡）、`/funnel`、`/cycle?group_by=`、`/channels`、`/trend?days=30`、`/export?type=xlsx`。
- T9.3 导出：用 openpyxl 生成多 sheet（漏斗/周期/渠道/明细），文件名带时间戳；PDF 导出用前端打印样式（Phase 2 再上服务端 PDF）。
- T9.4 前端看板：KPI 卡（在招职位/本期投递/待面试/已 offer/平均周期）+ 漏斗条形图 + 周期趋势折线 + 渠道对比柱状 + 导出按钮（Recharts）。
- T9.5 空态与口径提示：每个图旁标注口径（「周期 = 投递到入职中位数」），避免答辩被追问。
- T9.6 `tests/test_analytics.py`：造 20 条固定数据集，断言漏斗数与周期中位数与手算一致；导出 xlsx 行数正确。

**产出**：6 个分析接口、看板页、Excel 导出、口径文档、测试。

**DoD**：验收 A6「看板展示核心 KPI，数据准确」；固定数据集下漏斗/周期与手算完全一致；导出文件能用 Excel 打开且 sheet 齐全；首屏图表 ≤3s。

**坑**：周期统计要排除 `rejected`，否则「平均周期」没意义；跨月/时区边界按 `Asia/Shanghai` 切日；图表数据别在 SQL 里算太复杂，先出明细再 Python 聚合（数据量小，可读性优先）。

**PRD**：DA-01~05、§6.7、§14 A6。

---

### Step 10 — AI 成本控制（4 人日）【扩展·M9 之后】

**目标**：每次 AI 调用都记账，能看到「按职位/按用户」的 token 与花费，预算超了会告警。

**前置**：S4/S5/S7（有 AI 调用点）。

**任务**

- T10.1 `ai/client.py`：统一 LLM 客户端 —— 模型分级（`cheap` 用于解析、`standard` 用于匹配理由、`strong` 用于 JD/面试生成）、超时、重试、JSON 模式、Mock provider（无 Key 时按固定规则返回合法结构）。
- T10.2 计量：每次调用写 `ai_calls`（user/job/model/feature/input_tokens/output_tokens/cost/duration/status），价格表落 `core/pricing.py`（按模型配置单价，支持后续调价）。
- T10.3 缓存：`ai/cache.py` 按「feature + 输入内容 hash + 模型 + prompt 版本」缓存结果（SQLite 表，TTL 可配），命中不重复计费；缓存命中率要能统计。
- T10.4 预算：`cost_budgets` 表（部门/月/token 或金额上限），`services/cost.py` 检查当月消耗，达 80%/100% 写告警通知并（可选）拒绝新调用。
- T10.5 `api/v1/cost.py`：`/cost/summary?from=&to=&group_by=job|user|feature`、`/cost/budgets`（CRUD，Admin）、`/cost/calls`（明细分页）。
- T10.6 前端成本页（Admin）：用量趋势、Top 职位、缓存命中率、预算进度条。
- T10.7 `tests/test_cost.py`：一次调用恰好一条记录且金额=token×单价；缓存命中不新增记录；超预算返回 429 或降级。

**产出**：统一 AI 客户端、计量、缓存、预算、成本页。

**DoD**：任意一次解析/匹配/生成都能在 `ai_calls` 里查到且金额正确；缓存命中率 >30%（重复解析同一批）；预算达 100% 时新调用被拒并有明确错误码。

**坑**：`ai_calls` 的 `job_id` 允许为空（面试生成可能不绑职位）；成本单位统一到「元」并保留 6 位小数；别在请求线程里做同步记账（用同一事务写，或异步批量）。

**PRD**：CC-01~03、§6.9、§12「LLM 调用成本」。

---

### Step 11 — 前端整体打磨（5 人日）【扩展·核心只做必要样式】

**目标**：把 8 个页面收成一个像产品的东西：统一导航、统一表格/表单/空态/错误态，首屏 ≤3s。

**前置**：S3~S10 的页面已存在（哪怕粗糙）。

**任务**

- T11.1 信息架构：左侧导航按「招聘工作台 / 职位 / 候选人 / 面试 / 分析 / 设置」分组；Admin 组单独可见；面包屑与页签。
- T11.2 设计系统：颜色语义（状态色、分数色阶 0-100 四档）、表格密度、卡片、按钮层级、表单校验提示统一。
- T11.3 通用组件：`DataTable`（排序/筛选/分页/列显隐/批量选择）、`EmptyState`、`ErrorBoundary`、`Skeleton`、`ConfirmDialog`、`UploadDropzone`、`ScoreBar`。
- T11.4 交互细节：所有异步操作有 loading + 乐观更新回滚；表单离开未保存提示；错误 toast 带 request_id。
- T11.5 性能：路由级代码分割、图表懒加载、列表虚拟化（>200 行）、图片/简历预览按需加载；用 Next 的 `loading.tsx`。
- T11.6 兼容与响应式：Chrome/Firefox/Edge 近两版；1366 宽可用，表格在窄屏转卡片。
- T11.7 空/错/载三态全量走查清单（每页三态截图留档）。

**产出**：可用的一体化控制台、组件库、三态清单。

**DoD**：验收 G1 首屏 ≤3s（Lighthouse 截图）；验收 G3 三浏览器主流程可走；任意页面刷新不白屏（有 skeleton）；空数据页面不出现「暂无数据」以外的空白。

**坑**：不要在这一步重写业务逻辑；表格分页要服务端分页，前端全量拉会在大数据下卡死；Next 14 的 Server Component 与客户端状态混用容易踩坑，数据请求统一走 `lib/api.ts`。

**PRD**：§8.1 性能、§14.2 G1/G3。

---

### Step 12 — 安全与合规加固（4 人日）【扩展·三条底线已在核心内实现】

**目标**：把 PRD §10 的合规项落到代码里，能拿出证据。

**前置**：S2~S10。

**任务**

- T12.1 传输与头：HTTPS 说明（生产 Nginx 终止）、安全响应头（HSTS/CSP/X-Frame-Options）、CORS 白名单收紧。
- T12.2 静态加密：候选人手机号/邮箱/期望薪资用 Fernet 加密存储，`decrypt` 只在有权限的接口里做；密钥从 `.env` 读，禁止入库。
- T12.3 脱敏展示：列表页手机号 `138****1234`、邮箱 `a***@x.com`；「查看完整信息」需二次确认并写审计。
- T12.4 访问审计：所有「查看候选人完整信息 / 导出 / 删除 / 改角色」写 `audit_logs`（谁、何时、哪个对象、IP）。
- T12.5 限流：全局每用户 100 次/分钟（slowapi 或自研令牌桶），登录/进度查询/投递页单独更严；超限 429 带 `Retry-After`。
- T12.6 删除权（PIPL）：`DELETE /candidates/{id}/personal-data` 逻辑删除 PII（简历文件、联系方式）并保留审计；导出「已删除」证明。
- T12.7 OWASP 自查表：注入（全用 ORM 参数化）、XSS（React 转义 + 富文本白名单）、越权（每条路由有 `require_role` + 归属校验）、文件上传（类型/大小/名字清洗）、敏感信息（日志脱敏）。
- T12.8 越权测试矩阵：3 角色 × 6 类资源 = 18 条断言，写成 `tests/test_rbac.py`。

**产出**：加固后的接口、脱敏与审计、限流、删除权、自查表、18 条越权断言。

**DoD**：验收 G4「OWASP Top 10 基础测试」有自查表 + 证据；两账号互访候选人返回 404；日志里搜不到明文手机号；18 条断言全绿。

**坑**：加密字段一旦上线就不能再明文比较（去重要存 hash）；脱敏别在前端做（接口就该给脱敏值）；限流别把健康检查也限了。

**PRD**：§10.1/§10.2、§8.3、§14.2 G4。

---

### Step 13 — 测试与质量收口（4 人日）【扩展·核心只做 15 条关键用例】

**目标**：核心服务覆盖率 ≥80%，评测集能一键回归，改代码不怕。

**前置**：S1~S12。

**任务**

- T13.1 测试基建：`pytest.ini`（asyncio mode、`-q`、覆盖率插件）、`conftest.py`（临时 SQLite、`httpx.AsyncClient`、固定种子数据、Mock LLM 开关）。
- T13.2 覆盖清单：auth/jobs/parser/extractor/scorer/pipeline/analytics/cost 八个模块补到 ≥80%（按行覆盖，`pytest --cov` 出报告）。
- T13.3 接口契约测试：42 项需求里每个 P0 接口至少 1 条 happy path + 1 条错误路径。
- T13.4 评测回归：`scripts/eval_match.py`、`scripts/eval_parse.py` 纳入 CI 脚本，输出与 v1 基线对比（退化要红）。
- T13.5 前端最小测试：`vitest` 覆盖工具函数与 2 个关键组件（DataTable 排序、ScoreBar 色阶）。
- T13.6 冒烟脚本：`scripts/smoke.ps1` 起服务 → 建职位 → 传 3 份简历 → 匹配 → 断言 top1 是谁 → 造一条应聘并流转。
- T13.7 覆盖率报告与缺口说明：`docs/测试报告.md`（覆盖率、未覆盖原因、已知缺陷）。

**产出**：测试套件、覆盖率报告、冒烟脚本、评测基线。

**DoD**：`pytest` 全绿；八个核心模块覆盖率 ≥80%；冒烟脚本一条命令跑通；评测退化会失败。

**坑**：Mock LLM 要能"可控返回坏 JSON"，否则容错逻辑永远测不到；SQLite 临时库要 `:memory:` + StaticPool，否则并发用例互相污染。

**PRD**：§8.5 可维护性（覆盖率 ≥80%）。

---

### Step 14 — 部署与交付（4 人日）【扩展·核心只出 README + 启动说明】

**目标**：换台机器能跑起来，三份文档齐（API/用户/部署）。

**前置**：S13。

**任务**

- T14.1 `docker-compose.yml`：api / worker / web / postgres / redis（本机没 Docker 也要写，作为交付物与生产路径）。
- T14.2 `scripts/start-dev.ps1` / `start-prod.ps1`：本机进程方式（uvicorn + next start + 可选 PG），打印访问地址与默认账号。
- T14.3 `.env.example` 全量注释 + `docs/部署文档.md`（前置条件、步骤、常见故障 10 条、回滚）。
- T14.4 `docs/API文档.md`：OpenAPI 导出 + 关键接口示例（curl）+ 错误码表。
- T14.5 `docs/用户手册.md`：按角色写（Recruiter 建职位/传简历/看匹配；HM 审批/评估；Admin 配置/成本/审计）。
- T14.6 种子数据脚本：`scripts/seed.py`（1 公司 + 3 角色账号 + 3 职位 + 10 简历 + 20 应聘），演示不用现场造数据。
- T14.7 备份与恢复：`scripts/backup.ps1`（DB dump + uploads 打包）、恢复说明。

**产出**：compose、启动脚本、三份文档、种子数据、备份脚本。

**DoD**：验收 G5「API + 用户手册 + 部署文档」齐全；干净目录下按文档 15 分钟内跑起来；`seed.py` 后立刻能演示。

**坑**：文档里的命令必须自己照抄跑一遍（不然全是错的）；compose 里的路径/卷别写死本机绝对路径。

**PRD**：§9.3 部署、§14.2 G5。

---

### Step 15 — 验收与演示（3 人日）【扩展·核心只做演示脚本 + 简版验收】

**目标**：A1~A6 + G1~G5 每条都有证据；5 分钟能讲完一个闭环故事。

**前置**：S14。

**任务**

- T15.1 验收证据表：逐条填 `docs/验收报告.md`（判据 / 证据链接 / 结论），对应看板「3.验收清单」。
- T15.2 KPI 实测：解析准确率（6 份样例人工比对）、匹配一致率（30 条标注）、100 份批量耗时、100 并发下 P50、首屏时间 —— 全部记数字，不写「良好」。
- T15.3 演示脚本：`docs/演示脚本.md` —— 建职位(AI 生成 JD) → 传 10 份简历 → 看解析 → 一键匹配 → 点开理由 → 生成面试题 → 推进状态 → 收到通知 → 看板看漏斗 → 导出 Excel，每步一句话说明。
- T15.4 演示数据与截图：固定账号、固定数据集、8 张关键截图存 `docs/assets/`。
- T15.5 缺陷清单与 known issues：明确「Phase 2 才做」的 5 项，避免被当成 bug。
- T15.6 答辩 Q&A 预案：10 个必问问题（准确率怎么算、成本怎么控、隐私怎么保、偏见怎么办、为什么不用微服务）。

**产出**：验收报告、KPI 数字表、演示脚本、截图、Q&A。

**DoD**：6 条 A + 5 条 G 全部有「通过/不通过」和证据；演示脚本空跑一遍不卡壳（≤8 分钟）；KPI 数字与评测脚本输出一致。

**坑**：别在答辩前一天才跑评测；数字要能复现（脚本 + 固定数据），否则一问就穿。

**PRD**：§14 全部。

---

## 5. PRD 需求追溯矩阵（42 项）

| 编号 | 需求 | 优先级 | Phase | 实现步骤 | 验收方式 |
|---|---|:--:|:--:|:--:|---|
| UC-01 | 邮箱注册 | P0 | 1 | S2 | 注册成功 + 验证邮件入通知表 |
| UC-02 | 邮箱登录 | P0 | 1 | S2 | JWT 返回且可访问受保护接口 |
| UC-03 | 密码重置 | P0 | 1 | S2 | 重置后旧密码失效 |
| UC-04 | 个人信息管理 | P1 | 1 | S2/S11 | 改昵称头像后详情页生效 |
| UC-05 | API Key 管理 | P0 | 1 | S2 | 创建时全显、后续掩码、可撤销 |
| UC-06 | 用户列表管理 | P1 | 1 | S2 | Admin 可禁用/删除/改角色 |
| JM-01 | 职位创建（AI 辅助 JD） | P0 | 1 | S3 | 一键生成三段且可编辑保存 |
| JM-02 | 职位列表（搜索筛选） | P0 | 1 | S3 | 关键词/状态/部门筛选正确 |
| JM-03 | 职位审批 | P1 | 1 | S3 | HM 审批后状态变 published |
| JM-04 | 职位归档 | P1 | 1 | S3 | 归档后不出现在在招列表 |
| JM-05 | 职位模板 | P2 | 2 | — | 不实现 |
| RP-01 | 多格式解析 | P0 | 1 | S4 | PDF/Word/JPG/PNG 各 1 份成功 |
| RP-02 | 信息提取 | P0 | 1 | S4 | 姓名/电话/邮箱/经历准确率 ≥90% |
| RP-03 | 简历去重 | P1 | 1 | S4 | 同人两份只留一条 |
| RP-04 | 解析结果校对 | P1 | 1 | S4 | 可编辑并标记人工修改 |
| RP-05 | 批量解析 | P0 | 1 | S4 | 100 份异步完成且有进度 |
| SM-01 | 技能匹配 | P0 | 1 | S5 | 命中/缺失技能明细正确 |
| SM-02 | 经验匹配 | P0 | 1 | S5 | 年限差与相关度影响分数 |
| SM-03 | 综合评分与排名 | P0 | 1 | S5 | 排序与人工判断一致率 ≥80% |
| SM-04 | 匹配理由 | P1 | 1 | S5 | 五段理由可展示、可降级 |
| SM-05 | 人才库推荐 | P2 | 2 | — | 不实现 |
| IA-01 | 面试问题生成 | P0 | 1 | S7 | 6~8 题且引用具体经历 |
| IA-02 | 评估模板 | P1 | 1 | S7 | 维度权重可配、有锚点 |
| IA-03 | 面试记录 | P1 | 1 | S7 | 各维度评分 + 结论落库 |
| IA-04 | 面试报告 | P2 | 2 | — | 不实现 |
| RA-01 | 自动通知 | P0 | 1 | S8 | 4 类节点正确模板 |
| RA-02 | 面试安排 | P1 | 1 | S8 | ICS 可导入、冲突检测 |
| RA-03 | 流程状态管理 | P0 | 1 | S6 | 6 条合法链、非法跳转 400 |
| RA-04 | SLA 监控 | P1 | 1 | S8 | 超时标记 + 告警 |
| DA-01 | 招聘看板 | P0 | 1 | S9 | KPI 卡与漏斗数据准确 |
| DA-02 | 渠道分析 | P1 | 1 | S9 | 各渠道简历/面试/offer 对比 |
| DA-03 | 周期分析 | P1 | 1 | S9 | 中位数与手算一致 |
| DA-04 | 成本分析 | P1 | 1 | S9/S10 | 成本分项与 ai_calls 对得上 |
| DA-05 | 报表导出 | P1 | 1 | S9 | Excel 多 sheet 可打开 |
| CE-01 | 个性化投递页 | P1 | 1 | S8 | 匿名可投、品牌可配 |
| CE-02 | 进度查询 | P1 | 1 | S8 | 邮箱+编号可查、不泄漏评分 |
| CE-03 | 自动反馈 | P1 | 1 | S8 | 各节点候选人收到通知 |
| CE-04 | 满意度调查 | P2 | 2 | — | 不实现 |
| CC-01 | Token 用量统计 | P0 | 1 | S10 | 按职位/用户可查 |
| CC-02 | 成本预算 | P1 | 1 | S10 | 超预算告警并拦截 |
| CC-03 | 优化策略 | P1 | 1 | S10 | 模型分级 + 缓存命中率可证 |
| CC-04 | 成本报表 | P2 | 2 | — | 不实现 |

**覆盖自查**：A 线 18/37 ｜ B 线 33/37 ｜ C 线 37/37（Phase 2 的 5 项统一标「不实现」）。

---

## 6. 验收清单

### 6.1 PRD §14.1 Phase 1 验收

| 编号 | 验收项 | 判据（PRD 原文） | 本项目怎么证明 | 步骤 |
|:--:|---|---|---|---|
| A1 | 职位管理 | 创建/编辑/发布/归档全流程可用 | 录屏 + 4 条接口记录 + 状态流转日志 | S3 |
| A2 | 简历解析 | 四格式，准确率 ≥90% | 6 份样例 × 四字段人工比对表（准确率数字） | S4 |
| A3 | 人岗匹配 | 与 HR 评估一致性 ≥80% | 30 条标注集：三分类一致率 + Top-10 重合率 | S5 |
| A4 | AI 面试辅助 | 基于 JD 和简历生成个性化问题 | 10 个职位的生成结果 + 人工抽检「是否引用具体经历」 | S7 |
| A5 | 招聘流程 | 状态流转和自动通知正常 | 4 条主流程的通知记录（模板/渠道/时间） | S6/S8 |
| A6 | 数据分析 | 看板 KPI 准确 | 固定数据集下与手算一致的对照表 + 截图 | S9 |

### 6.2 PRD §14.2 通用验收

| 编号 | 验收项 | 判据 | 证明方式 | 步骤 |
|:--:|---|---|---|---|
| G1 | 页面性能 | 首屏 ≤3s | Lighthouse Desktop 报告（关键 4 页） | S11 |
| G2 | API 性能 | P50 ≤300ms | 100 并发 1 分钟压测（locust/ab）+ 分位表 | S12/S13 |
| G3 | 兼容性 | Chrome/Firefox/Edge 近 2 版 | 三浏览器主流程截图 | S11 |
| G4 | 安全性 | OWASP Top 10 基础测试 | 自查表 + 18 条越权断言 + 限流/脱敏证据 | S12 |
| G5 | 文档完整性 | API + 用户手册 + 部署文档 | 三份文档 + 15 分钟部署实录 | S14 |

### 6.3 必须自己写的 10 个测试用例（答辩会被抽查）

1. 弱密码注册 → 422，且错误信息说明「至少两类字符」。
2. 第 5 次错误密码 → 429，锁定期内正确密码也被拒。
3. 登出后旧 access token → 401（jti 黑名单生效）。
4. 非 Hiring Manager 审批职位 → 403。
5. 同一个人两份简历（不同格式）→ 候选人只有 1 条，简历挂 2 个文件。
6. 缺 must-have 技能的简历 → 分数低于同经验全命中者（且理由写明缺什么）。
7. `new → offer` 非法跳转 → 400，响应里列出允许的目标状态。
8. 拒绝候选人未填原因 → 422。
9. 两账号互访对方候选人 → 404（不是 403，避免探测）。
10. 一次 LLM 调用 → `ai_calls` 恰好 1 条且 cost 与 token×单价一致；缓存命中 → 0 条。

---

## 7. 风险与降级

| 编号 | 风险 | 触发信号 | 影响 | 应对（写进代码，不只写文档） |
|:--:|---|---|---|---|
| R1 | 解析准确率不达标 | 样例四字段 <90% | 验收 A2 挂 | 多解析器链 + 视觉 LLM 兜底 + 人工校对标记 |
| R2 | 匹配与 HR 判断不一致 | 一致率 <80% | 验收 A3 挂 | 权重可配 + 标注集调参 + HR 反馈回流 |
| R3 | 隐私泄漏 | 日志出现明文手机号 | 合规事故 | 统一日志脱敏 + 加密存储 + 审计 + 二次确认 |
| R4 | 批量解析超时 | 100 份 >10 分钟 | 演示失败 | 并发度可配 + 进度可查 + 失败重试 |
| R5 | LLM 返回结构漂移 | 前端渲染崩 | 功能不可用 | schema 校验 + 修复重试 + 模板兜底 |
| R6 | Token 成本超预算 | 单月超 500 元 | 账单 | 分级 + 缓存 + 预算拦截 + 用量页 |
| R7 | Redis 未装 | Celery 起不来 | 队列不可用 | `QUEUE_MODE` 可切内存；演示前装 Memurai |
| R8 | PG 起不来 | 迁移失败 | 无法演示 | 开发用 SQLite，演示前 3 天切 PG 并回归 |
| R9 | 状态机被绕过 | DB 里出现 new→offer | 数据不可信 | 只暴露 transition 接口 + 服务端校验 + 审计 |
| R10 | 范围蔓延 | 开始做视频面试/画像 | 延期 | 需求基线里 Phase 2 项标「不做」 |
| R11 | AI 偏见 | 某类群体系统性低分 | 合规/伦理质疑 | 输出不含性别/年龄/婚育字段；抽样做群体均分对照 |
| R12 | 单人项目进度崩 | 连续两周 DoD 未达 | 交不出 | 砍到 A 线闭环，先保「能演示」 |

---

## 8. 建议目录结构

```
TalentMatch/
├─ backend/
│  ├─ app/
│  │  ├─ main.py
│  │  ├─ core/            # config, database, security, deps, permissions, logging, rate_limit
│  │  ├─ models/          # models.py（13 张表）
│  │  ├─ schemas/         # user, job, candidate, resume, application, match, interview, notify, analytics, cost
│  │  ├─ api/v1/          # auth, users, jobs, resumes, candidates, applications, matching, interviews, notifications, analytics, cost, admin
│  │  ├─ services/        # storage, parser, normalize, dedupe, skill_dict, match_features, scorer, explain, pipeline, interview_gen, notify, sla, analytics, cost, export
│  │  ├─ ai/              # client, extractor, jd_writer, prompts/, cache, mock
│  │  ├─ workers/         # runner（TaskRunner 抽象）, celery_app, tasks
│  │  └─ tests/
│  ├─ alembic/
│  ├─ requirements.txt
│  └─ .env.example
├─ frontend/
│  ├─ app/                # (auth)/login, (dashboard)/jobs, candidates, matching, interviews, analytics, cost, admin, careers/[slug]
│  ├─ components/         # DataTable, ScoreBar, UploadDropzone, EmptyState, Skeleton, ...
│  └─ lib/api.ts
├─ docs/                  # 需求基线, ADR, spike, 评测, 验收报告, 演示脚本, 部署/API/用户手册
├─ samples/               # 6 份样例简历 + 标注集 + 固定数据集
├─ scripts/               # dev.ps1, migrate.ps1, seed.py, eval_match.py, eval_parse.py, smoke.ps1, backup.ps1
├─ data/                  # 运行期上传与 SQLite（.gitignore）
└─ docker-compose.yml
```

---

## 9. 节奏与演示脚本

### 9.1 核心版 6 周节奏（当前执行）

| 周 | 阶段 | 目标 | 周末必须能演示 |
|:--:|:--:|---|---|
| W1 | M0+M1 | 需求基线 + 环境 + 两个 spike + 9 张表 + 前端脚手架 | `/healthz` 正常；首页能开；标注集 20 条在手 |
| W2 | M2+M3 | 登录鉴权 + 三角色 + 职位管理 + 技能词典 | 三个角色分别登录；现场建职位并发布 |
| W3 | M4（上） | 上传 + 解析链 + 抽取 + 校对 | 传 1 份 PDF / 1 份 Word，结构化结果可改 |
| W4 | M4（下）+ M5（上） | 批量 + 去重 + 特征 + 评分 | 传 10 份不出错；排名出得来 |
| W5 | M5（下）+ M6 | 理由 + 评测 + 候选人/状态机/站内通知 | 匹配一致率有数字；状态能推进并收到通知 |
| W6 | M7+M8+M9 | 面试题 + 看板 + seed + 演示脚本 | 5 分钟完整演示：建职位→传简历→匹配→面试题→推状态→看板 |

**如果只剩 3 周**：`M0→M5` + M9 简版（约 22 人日），砍掉 M6~M8；演示改为「建职位→传简历→匹配→理由」。宁可少一个模块，也不要五个模块都半成品。

### 9.1b 扩展版 12 周节奏（完整 Phase 1，做完核心再上）

| 周 | 目标 | 周末必须能演示 |
|:--:|---|---|
| W1 | S0+S1 | `/healthz` + 13 张表 + 前端骨架 |
| W2 | S2 | 注册登录 + 三角色菜单 |
| W3 | S3 | 建职位 + AI 生成 JD + 审批发布 |
| W4 | S4（上半） | 单份四格式解析成功 |
| W5 | S4（下半） | 100 份批量 + 进度 + 去重 + 校对 |
| W6 | S5（上半） | 规则评分 + 排名表 |
| W7 | S5（下半）+ S6 | 匹配理由 + 评测一致率 + 状态流转 |
| W8 | S7+S8 | 面试题生成 + 通知 + 投递页 |
| W9 | S9 | 漏斗/周期/渠道/导出 |
| W10 | S10+S11 | 成本页 + 前端统一 |
| W11 | S12+S13 | 越权矩阵 + 覆盖率 80% |
| W12 | S14+S15 | 部署 + A1~A6 验收证据 |

**每周五固定动作**：跑 `smoke.ps1` → 存截图 → 更新看板状态 → 写一段「本周坑与解法」（答辩素材）。

### 9.2 5 分钟演示脚本（评委视角）

1. 登录 Recruiter → 建职位，点「AI 生成 JD」，改两个字保存 → 提审 → 切 Hiring Manager 审批 → 发布（40s）。
2. 上传 10 份简历（混合 PDF/Word/图片）→ 进度条 → 打开一份看解析表单，改一个字段（50s）。
3. 回职位页点「智能匹配」→ 排名表 → 展开第 1 名的理由（命中/缺失技能）→ 标记一份「不合适」（50s）。
4. 选第 1 名 → 生成面试题（8 题）→ 勾选 3 题进下一轮（40s）。
5. 把候选人推到 interview → 通知中心出现邀请邮件（含 .ics）（40s）。
6. 打开分析看板：漏斗 + 周期 + 渠道 → 导出 Excel（40s）。
7. 切 Admin：成本页（本月 token/金额/缓存命中率）+ 审计日志（刚才谁看了候选人）（40s）。

---

## 10. 开工第一周：今天就能做的 10 个动作

1. 建 `TalentMatch/` 目录与 `docs/`，把 PRD 复制进 `docs/`（版本锚点）。
2. 把 42 项需求抄成 `docs/需求基线.md`（直接照第 5 章的表，改状态列）。
3. 写 `docs/ADR-001`（技术栈 + 5 处偏离 + 不做什么），30 分钟内完成，不要纠结。
4. 确认 LLM Key：有则写 `.env`，没有则先按 Mock 走（`LLM_MOCK=1`），不要卡在这里。
5. 跑通 conda `py311`：`pip install` 一次性装 T1.2 的包，记录耗时与报错。
6. 用 `npm.cmd create next-app` 建前端，确认 `npm.cmd run dev` 能开页面（注意不是 `npm`）。
7. 抽 6 份真实中文简历放 `samples/`（表格/双栏/扫描/Word/图片/超长各 1），这是后面所有评测的地基。
8. 人工给 30 份简历 × 1 个职位打标签，写清口径 → `docs/标注集-v1.csv`。
9. 跑 Spike A/B（解析 + LLM 抽取），只记录数字，不做优化。
10. 建 git 仓库，`main` 保护，第一笔提交是「docs: 需求基线 + ADR + 环境清单」。

---

## 附录 A：三个必须先定死的口径

### A.1 匹配评分公式（S5 要落成代码）

```
skill_score = 0.7 * must_have_coverage + 0.3 * nice_to_have_coverage
              （must_have_coverage < 1 时整体 × 0.6 惩罚）
exp_score   = 年限达标(0~0.6) + 相关领域加分(0~0.3) + 稳定性加分(0~0.1)
edu_score   = 学历满足 1.0 / 超配 0.9 / 不满足 0.5
other       = 地点匹配 0.5 + 薪资区间重叠 0.3 + 行业相关 0.2
final       = 100 * (0.50*skill + 0.30*exp + 0.12*edu + 0.08*other)
```

- 硬门槛（must-have）在 JD 的 `skills` 里单独标记，前端可勾选。
- 权重写在 `core/scoring_config.py`，用标注集调 3 组并存档对比。

### A.2 简历结构化字段（S4 的 schema，前后端/LLM 三方共用一份）

```
name, phone, email, city, birth_year(可选), education[{school,degree,major,start,end}],
work[{company,title,start,end,description}], skills[{name,years,level}],
projects[{name,role,tech,summary}], certificates[], expected_salary, source_channel
+ field_confidence{field: 0~1} + parse_meta{method, pages, duration_ms}
```

### A.3 应聘状态机（S6 的唯一真相）

```
new → screening → interview → offer → hired
         ↘ rejected（必须带 reject_reason）
任意非终态 → rejected；rejected/hired 为终态（Admin 可走 `reopen` 特殊接口并写审计）
```

---

## 附录 B：与 PRD 的对照阅读顺序

1. PRD §3.2（边界）→ 本文 §1.2（哪些不做）。
2. PRD §6（功能）→ 本文 §4（每步做什么）+ §5（追溯）。
3. PRD §7（数据模型）→ 本文 S1（13 张表，PRD 只给了 4 张，其余是补的）。
4. PRD §8/§10（非功能/合规）→ 本文 S12/S13（加固与测试）。
5. PRD §11（里程碑）→ 本文 §3.4（对照表）。
6. PRD §14（验收）→ 本文 §6（怎么证明）。

> 口径说明：总览表的人日是「步骤级含联调」，任务看板是 0.5~1 天粒度细估，合计会比总览高约 10%（缓冲）。排期看总览，拆分看任务清单。
