# TalentMatch 改造计划（基于 Resume-Assistant 现有代码）

> ⚠️ **本文已被取代，仅作历史参考。**
> 当前有效文档：**《TalentMatch_项目设计方案_V1.md》**（架构与分阶段）、**《TalentMatch_数据库设计_V1.md》**（20 张表）、**《TalentMatch_对话式交互与产品画面_V1.md》**（交互与界面）。
> 本文写作时尚未确定「从零开发 + MinIO 对象存储」这两个决定，其中技术栈、存储、建表数量相关结论已过时。

> 底座：`P1M0U/Resume-Assistant`（MIT），已克隆到项目根目录，`docs/` 是我们的计划文档。
> 现状：**C 端「简历打分 + 岗位推荐」工具**。后端 MySQL 只有 `user`、`llm_config` 两张表；没有职位、候选人、应聘、AI 计量；只有 `is_admin`，没有角色。
> 目标：按 PRD 改造成 **B 端招聘平台**，保留它已经做好的东西，只补缺的。

---

## 一、现有代码里能直接用的（不要重写）

| 能力 | 位置 | 改造后怎么用 |
|---|---|---|
| FastAPI 骨架 + 统一响应 + 全局异常 | `backend/main.py`、`core/response.py` | 原样保留，只改 title 和 CORS |
| JWT + bcrypt | `core/security.py` | 加角色判定，其余不动 |
| 多厂商 LLM 路由 + 每用户 BYOK | `agentics/chat.py`、`services/llm_config_service.py` | 匹配理由、面试题生成直接复用 |
| PDF/DOCX 解析 | `agentics/utils/file_parser.py` | 简历解析的文本层，保留 |
| LangChain Agent 封装 | `agentics/agents/base_agent.py` | 新增两个 Agent 继承它 |
| 向量检索（Chroma） | `agentics/rag/` | 保留，匹配时可选做语义召回 |
| Vue3 + Element Plus + Pinia + 路由守卫 | `resume_vue/src/` | 新增页面按现有 `components/ + composables/` 风格写 |
| 测试基建（SQLite 内存库） | `backend/tests/conftest.py` | 新表加进 `create_all` 前的导入列表 |
| Docker/Jenkins/Makefile | 根目录 | 最后再改 compose 服务名 |

## 二、必须新写的（按 PRD 缺口）

| 缺口 | 现状 | 要补的 |
|---|---|---|
| 数据模型 | 2 张表 | 职位、候选人、简历、简历文件、应聘、匹配结果、AI 调用记录（7 张） |
| 角色权限 | 只有 `is_admin` | `role` 字段 + `require_role()` + 前端菜单分离（recruiter/manager/admin） |
| 职位管理 | 无 | 职位 CRUD、发布/关闭、技能词表、AI 生成 JD |
| 简历落库 | 分析完只回给前端，不存库 | 上传即建候选人 + 简历记录，去重、校对 |
| 匹配打分 | 只有"推荐岗位"的 LLM 结果，无分数公式 | 规则打分（技能/经验/学历）+ 理由 + 排名 + 缓存落库 |
| 应聘流程 | 无 | 状态机（new→screening→interview→offer→hired/rejected）+ 流转历史 |
| AI 面试题 | 无 | 生成 6~8 题（引用具体项目/缺口）+ 缓存 |
| AI 计量 | 无 | `ai_calls` 记录 token/费用，按职位聚合 |
| 看板 | 无 | 漏斗/周期/渠道 3 个查询 + 前端一页 |

## 三、改造阶段（约 17.5 人日）

| 阶段 | 干什么 | 完成标准 | 天 |
|:--:|---|---|:--:|
| **0** | 把现有项目跑起来：装依赖、配 `env.yaml`、跑测试、起前端 | `/docs` 能开；`pytest` 全绿；前端首页能开 | 1 |
| **1** | 数据模型扩到 8 张表 + SQLite 支持 + 种子脚本 | 库里 8 张表；seed 出 3 个角色账号 | 2 |
| **2** | 角色权限：`role` 字段、`require_role`、前端菜单 | recruiter 调 admin 接口 403；菜单随角色变 | 1.5 |
| **3** | 职位管理：CRUD + 发布 + 技能词表 + AI 生成 JD | 建职位→发布→列表筛选可用 | 2 |
| **4** | 简历上传→候选人落库：解析、去重、校对、批量 | 传 3 份出 3 个候选人；同人去重 | 3 |
| **5** | 匹配打分：规则评分 + 理由 + 排名 + 缓存 | 出排名，点开有命中/缺失技能 | 3 |
| **6** | 应聘流程 + AI 面试题 | 拖状态成功、非法跳转被拒；生成 8 题 | 2.5 |
| **7** | AI 计量 + 看板 + 改名收尾 | 每次调用有记录；看板与库一致；README 更新 | 2.5 |

**只剩一周**：做 0→1→2→3 + 7 的 README，演示到"建职位 + 登录角色"。

## 四、每步改哪些文件

| 阶段 | 新增 | 修改 |
|---|---|---|
| 1 | `dbs/mysql/models/{job,candidate,resume,resume_file,application,match_result,ai_call}.py`、`scripts/seed.py` | `models/user.py`（加 role）、`database.py`（SQLite 支持）、`init_db()` 导入列表、`conftest.py` |
| 2 | `core/permissions.py` | `core/security.py`、`routers/v1/user_router.py`、`schemas/user.py`、前端 `router/index.ts`、`stores/user.ts` |
| 3 | `routers/v1/job_router.py`、`services/job_service.py`、`schemas/job.py`、`services/skill_dict.py`、前端 `JobListView.vue`/`JobEditView.vue` | `main_router.py`、现有 `job_router.py`（原来的"岗位推荐"改名避免冲突） |
| 4 | `services/resume_ingest.py`、`services/dedupe.py`、`models/resume.py` 配套、前端 `CandidateListView.vue` | `services/resume_service.py`、`routers/v1/resume_router.py`、`ResumeAnalysisView.vue` |
| 5 | `services/matcher.py`、`services/explain.py`、`routers/v1/match_router.py`、前端 `MatchView.vue` | `agentics/agents/job_agent.py`（复用其提示词生成理由） |
| 6 | `services/pipeline.py`、`routers/v1/application_router.py`、`agentics/agents/interview_agent.py`、`prompts/interview_prompt.py`、前端 `PipelineView.vue` | `main_router.py`、`schemas/` |
| 7 | `core/token_tracker.py`、`services/analytics.py`、`routers/v1/analytics_router.py`、`routers/v1/cost_router.py`、前端 `DashboardView.vue` | `agentics/chat.py`（调用后记账）、`README.md`、`docker-compose.yml` |

## 五、四条不能破的规矩

1. **技术栈以现有代码为准**：Vue3 / MySQL（可切 SQLite）/ 无 Celery / 无 MinIO。PRD 9.1 的 Next.js+PG+Celery 不照搬，写进 `docs/ADR` 说明理由。
2. **不写没有的成果**：PRD 里的「效率提升 10 倍」「成本降 30%」是产品目标，README 只能写实测口径（如"__ 份样本，一致率 __%"）。
3. **保留 MIT 署名**：README 开头注明"基于 P1M0U/Resume-Assistant 二次开发"。
4. **每阶段跑一次 `pytest`**：新表、新接口都要在 SQLite 内存库测试里过，不许"等我本地 MySQL 起来再测"。

## 六、和老计划的差别

之前按"从零建 9 阶段 / 28.5 人日"规划；现在有底座，**17.5 人日**就能到同样终点（省掉骨架、鉴权、LLM 接入、前端脚手架、文件解析的重复建设）。
`docs/TalentMatch_阶段任务计划.md` 仍然有效，只是阶段 1/2/3 的内容被"复用现有代码"替代，验收标准不变。
