# TalentMatch 数据字典（V1）

> ⚠️ **本文已被取代，仅作历史参考。**
> 当前有效文档：**《TalentMatch_项目设计方案_V1.md》**（架构与分阶段）、**《TalentMatch_数据库设计_V1.md》**（20 张表）、**《TalentMatch_对话式交互与产品画面_V1.md》**（交互与界面）。
> 本文写作时尚未确定「从零开发 + MinIO 对象存储」这两个决定，其中技术栈、存储、建表数量相关结论已过时。

> 生成时间：2026-11-19 19:57　|　生成方式：`scripts/gen_data_dictionary.py` 从模型代码自动导出
> 口径：字段、类型、可空、默认值、外键、索引均读自 SQLAlchemy `Base.metadata`，与代码一致；中文说明维护在脚本里。

---

## 一、总览

当前共 **10 张表**：原有 2 张 + 本次改造新增 8 张，合计 **120 个字段**、**15 个外键**、**33 个索引**。

| # | 表名 | 中文名 | 用途 | 字段数 | 外键数 | 来源 |
|:--:|---|---|---|:--:|:--:|---|
| 1 | `user` | 用户表 | 账号、登录凭证与角色；TalentMatch 的三角色（招聘专员/用人经理/管理员）落在 role 字段 | 8 | 0 | 原有（改造后新增 role） |
| 2 | `llm_configs` | 大模型配置表 | 每用户可配置多个厂商（智谱/DeepSeek 等）的 API Key，至多一个激活；Key 用 Fernet 加密存储 | 13 | 0 | 原有 |
| 3 | `job` | 职位表 | 招聘职位（JD、技能要求、薪资、发布状态），是整条招聘链路的起点 | 16 | 1 | 新增 |
| 4 | `candidate` | 候选人表 | 候选人档案；同一候选人多份简历只保留一条，靠 dedupe_key 去重 | 18 | 1 | 新增 |
| 5 | `resume_file` | 简历原始文件表 | 上传的 PDF/DOCX 文件元信息与解析状态，sha256 用于避免重复解析 | 11 | 1 | 新增 |
| 6 | `resume` | 简历解析结果表 | 结构化字段 + 字段级置信度，支撑人工校对与后续匹配 | 9 | 2 | 新增 |
| 7 | `application` | 应聘记录表 | 谁投了哪个职位、当前处于哪一步、来源渠道；状态机与周期分析的数据源 | 11 | 3 | 新增 |
| 8 | `application_stage_history` | 应聘状态流转历史表 | 每次状态变更一条记录，前端时间线与阶段停留时长依赖它 | 7 | 2 | 新增 |
| 9 | `match_result` | 人岗匹配结果表 | 可解释的匹配评分（技能/经验/学历/其他）与命中/缺失技能明细，支持缓存复用 | 15 | 3 | 新增 |
| 10 | `ai_call` | AI 调用记录表 | 每次大模型调用的 token、费用、耗时，用于成本统计与预算控制 | 12 | 2 | 新增 |

**状态字段速查**（写代码/联调时最常用，避免记错枚举值）

| 表.字段 | 取值 |
|---|---|
| `user.role` | `recruiter` 招聘专员 / `manager` 用人经理 / `admin` 管理员 |
| `job.status` | `draft` 草稿 → `published` 招聘中 → `closed` 已关闭 → `archived` 已归档 |
| `resume_file.status` | `pending` 待解析 / `parsing` 解析中 / `success` 成功 / `failed` 失败 |
| `application.status` | `new` → `screening` → `interview` → `offer` → `hired`；任意非终态 → `rejected`（必填原因） |
| `ai_call.feature` | `resume_parse` / `jd_generate` / `match_explain` / `interview_generate` / `resume_score` |

---

## 二、逐表说明

### `user` —— 用户表

**用途**：账号、登录凭证与角色；TalentMatch 的三角色（招聘专员/用人经理/管理员）落在 role 字段

| 字段 | 类型 | 可空 | 默认 | 约束 | 外键 | 说明 |
|---|---|:--:|---|---|---|---|
| `id` | INTEGER | 否 | — | PK | — | 主键 |
| `name` | VARCHAR(255) | 否 | — | UQ | — | 用户名（唯一） |
| `password` | VARCHAR(255) | 否 | — | — | — | bcrypt 哈希后的密码，绝不存明文 |
| `email` | VARCHAR(255) | 否 | — | UQ | — | 邮箱（唯一），也用于登录与通知 |
| `create_time` | DATETIME | 是 | now() | — | — | 创建时间 |
| `latest_update` | DATETIME | 是 | now() | — | — | 最后一次更新时间 |
| `is_admin` | BOOLEAN | 是 | false | — | — | 旧版管理员标记（兼容保留），role=admin 时同步为真 |
| `role` | VARCHAR(20) | 是 | `recruiter` | — | — | 角色：recruiter 招聘专员 / manager 用人经理 / admin 管理员 |

**索引 / 约束**

- 索引 `ix_user_email`: (email)
- 索引 `ix_user_name`: (name)
- 索引 `ix_user_id`: (id)

### `llm_configs` —— 大模型配置表

**用途**：每用户可配置多个厂商（智谱/DeepSeek 等）的 API Key，至多一个激活；Key 用 Fernet 加密存储

| 字段 | 类型 | 可空 | 默认 | 约束 | 外键 | 说明 |
|---|---|:--:|---|---|---|---|
| `id` | INTEGER | 否 | — | PK | — | 主键 |
| `user_id` | INTEGER | 否 | — | — | — | 所属用户（逻辑外键，未建物理约束） |
| `create_time` | DATETIME | 是 | now() | — | — | 创建时间 |
| `provider` | VARCHAR(50) | 否 | — | — | — | 厂商标识：zhipu / deepseek / … |
| `api_key` | VARCHAR(512) | 否 | '' | — | — | API Key（Fernet 加密后的密文） |
| `base_url` | VARCHAR(255) | 否 | '' | — | — | 厂商 OpenAI 兼容接口地址 |
| `chat_model` | VARCHAR(100) | 否 | '' | — | — | 对话模型名 |
| `embedding_model` | VARCHAR(100) | 否 | '' | — | — | 向量模型名（可为空） |
| `temperature` | FLOAT | 否 | `0.7` | — | — | 采样温度 |
| `max_tokens` | INTEGER | 否 | `4096` | — | — | 单次最大输出 token |
| `streaming` | BOOLEAN | 否 | false | — | — | 是否启用流式输出 |
| `is_active` | BOOLEAN | 否 | false | — | — | 是否为当前激活厂商（每用户至多一个） |
| `updated_at` | DATETIME | 是 | now() | — | — | 更新时间 |

**索引 / 约束**

- 索引 `ix_llm_configs_id`: (id)
- 索引 `ix_llm_configs_user_id`: (user_id)
- 约束 UniqueConstraint(`uq_user_provider`: user_id, provider)

### `job` —— 职位表

**用途**：招聘职位（JD、技能要求、薪资、发布状态），是整条招聘链路的起点

| 字段 | 类型 | 可空 | 默认 | 约束 | 外键 | 说明 |
|---|---|:--:|---|---|---|---|
| `id` | INTEGER | 否 | — | PK | — | 主键 |
| `title` | VARCHAR(200) | 否 | — | — | — | 职位名称 |
| `department` | VARCHAR(100) | 是 | — | — | — | 所属部门 |
| `location` | VARCHAR(100) | 是 | — | — | — | 工作地点 |
| `headcount` | INTEGER | 是 | `1` | — | — | 招聘人数 |
| `description` | TEXT | 是 | — | — | — | 职位描述（职责） |
| `requirements` | TEXT | 是 | — | — | — | 任职要求 |
| `skills` | JSON | 是 | `[]` | — | — | 技能要求列表（已按技能词表归一） |
| `must_have_skills` | JSON | 是 | `[]` | — | — | 必备技能子集，缺失时要扣分 |
| `salary_min` | INTEGER | 是 | — | — | — | 月薪下限（K） |
| `salary_max` | INTEGER | 是 | — | — | — | 月薪上限（K） |
| `status` | VARCHAR(20) | 否 | `draft` | — | — | 状态：draft 草稿 / published 招聘中 / closed 已关闭 / archived 已归档 |
| `jd_source` | VARCHAR(20) | 是 | `manual` | — | — | JD 来源：manual 手写 / ai 生成后人工修改 |
| `created_by` | INTEGER | 是 | — | — | user.id | 创建人（user.id） |
| `create_time` | DATETIME | 是 | now() | — | — | 创建时间 |
| `update_time` | DATETIME | 是 | now() | — | — | 更新时间 |

**索引 / 约束**

- 索引 `ix_job_id`: (id)
- 索引 `ix_job_status`: (status)

### `candidate` —— 候选人表

**用途**：候选人档案；同一候选人多份简历只保留一条，靠 dedupe_key 去重

| 字段 | 类型 | 可空 | 默认 | 约束 | 外键 | 说明 |
|---|---|:--:|---|---|---|---|
| `id` | INTEGER | 否 | — | PK | — | 主键 |
| `name` | VARCHAR(100) | 否 | — | — | — | 姓名 |
| `phone` | VARCHAR(30) | 是 | — | — | — | 手机号（后续按隐私要求加密/脱敏展示） |
| `email` | VARCHAR(255) | 是 | — | — | — | 邮箱 |
| `city` | VARCHAR(50) | 是 | — | — | — | 所在城市 |
| `education_level` | VARCHAR(20) | 是 | — | — | — | 最高学历：大专/本科/硕士/博士 |
| `school` | VARCHAR(100) | 是 | — | — | — | 毕业院校 |
| `major` | VARCHAR(100) | 是 | — | — | — | 专业 |
| `years_experience` | FLOAT | 是 | — | — | — | 工作年限（年，浮点，支持 3.5 年） |
| `skills` | JSON | 是 | `[]` | — | — | 技能标签列表（已归一） |
| `latest_company` | VARCHAR(200) | 是 | — | — | — | 最近一段工作的公司 |
| `latest_title` | VARCHAR(100) | 是 | — | — | — | 最近一段工作的职位 |
| `source_channel` | VARCHAR(30) | 是 | `manual` | — | — | 来源渠道：官网/内推/猎头/其他 |
| `resume_text` | TEXT | 是 | — | — | — | 最近一份简历的纯文本（供匹配与检索） |
| `dedupe_key` | VARCHAR(64) | 是 | — | UQ | — | 去重键（邮箱或手机号归一），唯一约束 |
| `created_by` | INTEGER | 是 | — | — | user.id | 录入人（user.id） |
| `create_time` | DATETIME | 是 | now() | — | — | 创建时间 |
| `update_time` | DATETIME | 是 | now() | — | — | 更新时间 |

**索引 / 约束**

- 索引 `ix_candidate_dedupe_key`: (dedupe_key)
- 索引 `ix_candidate_phone`: (phone)
- 索引 `ix_candidate_email`: (email)
- 索引 `ix_candidate_id`: (id)

### `resume_file` —— 简历原始文件表

**用途**：上传的 PDF/DOCX 文件元信息与解析状态，sha256 用于避免重复解析

| 字段 | 类型 | 可空 | 默认 | 约束 | 外键 | 说明 |
|---|---|:--:|---|---|---|---|
| `id` | INTEGER | 否 | — | PK | — | 主键 |
| `candidate_id` | INTEGER | 是 | — | — | candidate.id | 归属候选人（解析成功前可为空） |
| `original_name` | VARCHAR(255) | 否 | — | — | — | 上传时的原始文件名 |
| `stored_path` | VARCHAR(500) | 是 | — | — | — | 落盘相对路径（按 UUID 命名，不含姓名） |
| `size` | INTEGER | 是 | — | — | — | 文件大小（字节） |
| `sha256` | VARCHAR(64) | 是 | — | UQ | — | 文件内容指纹，唯一；同文件重复上传直接命中 |
| `mime` | VARCHAR(100) | 是 | — | — | — | MIME 类型 |
| `status` | VARCHAR(20) | 否 | `pending` | — | — | 解析状态：pending 待解析 / parsing 解析中 / success 成功 / failed 失败 |
| `error` | TEXT | 是 | — | — | — | 解析失败原因（给 HR 看的一句话） |
| `create_time` | DATETIME | 是 | now() | — | — | 上传时间 |
| `parsed_time` | DATETIME | 是 | — | — | — | 解析完成时间 |

**索引 / 约束**

- 索引 `ix_resume_file_candidate_id`: (candidate_id)
- 索引 `ix_resume_file_sha256`: (sha256)
- 索引 `ix_resume_file_id`: (id)
- 索引 `ix_resume_file_status`: (status)

### `resume` —— 简历解析结果表

**用途**：结构化字段 + 字段级置信度，支撑人工校对与后续匹配

| 字段 | 类型 | 可空 | 默认 | 约束 | 外键 | 说明 |
|---|---|:--:|---|---|---|---|
| `id` | INTEGER | 否 | — | PK | — | 主键 |
| `candidate_id` | INTEGER | 否 | — | — | candidate.id | 归属候选人 |
| `file_id` | INTEGER | 是 | — | — | resume_file.id | 来源文件（resume_file.id） |
| `structured` | JSON | 是 | `{}` | — | — | 结构化内容：姓名/联系方式/教育/工作/项目/技能等 |
| `plain_text` | TEXT | 是 | — | — | — | 简历纯文本（原文） |
| `confidence` | JSON | 是 | `{}` | — | — | 字段级置信度 0~1，前端据此标黄提示校对 |
| `parser` | VARCHAR(30) | 是 | — | — | — | 解析器标识：pypdf / python-docx / 视觉模型 |
| `is_primary` | BOOLEAN | 是 | false | — | — | 是否为该候选人的主简历 |
| `create_time` | DATETIME | 是 | now() | — | — | 解析入库时间 |

**索引 / 约束**

- 索引 `ix_resume_fk_file`: (file_id)
- 索引 `ix_resume_id`: (id)
- 索引 `ix_resume_candidate_id`: (candidate_id)

### `application` —— 应聘记录表

**用途**：谁投了哪个职位、当前处于哪一步、来源渠道；状态机与周期分析的数据源

| 字段 | 类型 | 可空 | 默认 | 约束 | 外键 | 说明 |
|---|---|:--:|---|---|---|---|
| `id` | INTEGER | 否 | — | PK | — | 主键 |
| `job_id` | INTEGER | 否 | — | — | job.id | 应聘职位（job.id） |
| `candidate_id` | INTEGER | 否 | — | — | candidate.id | 应聘候选人（candidate.id） |
| `status` | VARCHAR(20) | 否 | `new` | — | — | 状态：new/screening/interview/offer/hired/rejected |
| `source` | VARCHAR(30) | 是 | `manual` | — | — | 本此投递的来源渠道 |
| `match_score` | FLOAT | 是 | — | — | — | 投递时的匹配分（冗余，便于列表排序） |
| `applied_at` | DATETIME | 否 | now() | — | — | 投递时间 |
| `stage_entered_at` | DATETIME | 是 | now() | — | — | 进入当前阶段的时间（算阶段停留时长用） |
| `rejected_reason` | TEXT | 是 | — | — | — | 淘汰原因（rejected 时必填） |
| `created_by` | INTEGER | 是 | — | — | user.id | 操作人（user.id） |
| `update_time` | DATETIME | 是 | now() | — | — | 更新时间 |

**索引 / 约束**

- 索引 `ix_application_status`: (status)
- 索引 `ix_application_id`: (id)
- 索引 `ix_application_candidate_id`: (candidate_id)
- 索引 `ix_application_job_id`: (job_id)
- 约束 UniqueConstraint(`uq_application_job_candidate`: job_id, candidate_id)

### `application_stage_history` —— 应聘状态流转历史表

**用途**：每次状态变更一条记录，前端时间线与阶段停留时长依赖它

| 字段 | 类型 | 可空 | 默认 | 约束 | 外键 | 说明 |
|---|---|:--:|---|---|---|---|
| `id` | INTEGER | 否 | — | PK | — | 主键 |
| `application_id` | INTEGER | 否 | — | — | application.id | 所属应聘记录 |
| `from_status` | VARCHAR(20) | 是 | — | — | — | 变更前状态 |
| `to_status` | VARCHAR(20) | 否 | — | — | — | 变更后状态 |
| `operator_id` | INTEGER | 是 | — | — | user.id | 操作人（user.id） |
| `note` | TEXT | 是 | — | — | — | 备注（如淘汰原因） |
| `create_time` | DATETIME | 是 | now() | — | — | 变更时间 |

**索引 / 约束**

- 索引 `ix_application_stage_history_id`: (id)
- 索引 `ix_application_stage_history_application_id`: (application_id)

### `match_result` —— 人岗匹配结果表

**用途**：可解释的匹配评分（技能/经验/学历/其他）与命中/缺失技能明细，支持缓存复用

| 字段 | 类型 | 可空 | 默认 | 约束 | 外键 | 说明 |
|---|---|:--:|---|---|---|---|
| `id` | INTEGER | 否 | — | PK | — | 主键 |
| `job_id` | INTEGER | 否 | — | — | job.id | 职位 |
| `candidate_id` | INTEGER | 否 | — | — | candidate.id | 候选人 |
| `resume_id` | INTEGER | 是 | — | — | resume.id | 参与计算的简历版本 |
| `score` | FLOAT | 否 | — | — | — | 综合分 0~100 |
| `skill_score` | FLOAT | 是 | — | — | — | 技能得分 |
| `exp_score` | FLOAT | 是 | — | — | — | 经验得分 |
| `edu_score` | FLOAT | 是 | — | — | — | 学历得分 |
| `other_score` | FLOAT | 是 | — | — | — | 其他（地点/薪资/行业）得分 |
| `matched_skills` | JSON | 是 | `[]` | — | — | 命中的技能列表 |
| `missing_skills` | JSON | 是 | `[]` | — | — | 缺失的技能列表 |
| `summary` | TEXT | 是 | — | — | — | 一句话结论，列表直接展示 |
| `detail` | JSON | 是 | `{}` | — | — | 完整理由明细（各维度扣分原因、经验差等） |
| `fingerprint` | VARCHAR(64) | 是 | — | — | — | 计算指纹（职位版本 + 简历内容 hash），缓存判断用 |
| `create_time` | DATETIME | 是 | now() | — | — | 计算时间 |

**索引 / 约束**

- 索引 `ix_match_result_id`: (id)
- 索引 `ix_match_result_candidate_id`: (candidate_id)
- 索引 `ix_match_result_fingerprint`: (fingerprint)
- 索引 `ix_match_result_job_id`: (job_id)

### `ai_call` —— AI 调用记录表

**用途**：每次大模型调用的 token、费用、耗时，用于成本统计与预算控制

| 字段 | 类型 | 可空 | 默认 | 约束 | 外键 | 说明 |
|---|---|:--:|---|---|---|---|
| `id` | INTEGER | 否 | — | PK | — | 主键 |
| `user_id` | INTEGER | 是 | — | — | user.id | 触发调用的用户 |
| `job_id` | INTEGER | 是 | — | — | job.id | 关联职位（可为空，如 JD 生成时尚未落库） |
| `feature` | VARCHAR(50) | 否 | — | — | — | 调用场景：resume_parse / jd_generate / match_explain / interview_generate / resume_score |
| `provider` | VARCHAR(50) | 是 | — | — | — | 厂商标识 |
| `model` | VARCHAR(100) | 是 | — | — | — | 模型名 |
| `input_tokens` | INTEGER | 是 | `0` | — | — | 输入 token 数 |
| `output_tokens` | INTEGER | 是 | `0` | — | — | 输出 token 数 |
| `cost` | FLOAT | 是 | `0.0` | — | — | 费用（元，保留 6 位小数） |
| `duration_ms` | INTEGER | 是 | — | — | — | 调用耗时（毫秒） |
| `status` | VARCHAR(20) | 是 | `success` | — | — | 结果：success / failed |
| `create_time` | DATETIME | 是 | now() | — | — | 调用时间 |

**索引 / 约束**

- 索引 `ix_ai_call_id`: (id)
- 索引 `ix_ai_call_feature`: (feature)
- 索引 `ix_ai_call_job_id`: (job_id)
- 索引 `ix_ai_call_user_id`: (user_id)
- 索引 `ix_ai_call_create_time`: (create_time)

---

## 三、实体关系

```
user ──1:N──> job                (job.created_by)
user ──1:N──> candidate          (candidate.created_by)
user ──1:N──> ai_call            (ai_call.user_id)
user ──1:N──> llm_configs        (llm_configs.user_id，逻辑外键)

candidate ──1:N──> resume_file   (简历原始文件，可多份)
candidate ──1:N──> resume        (解析结果，与文件一一对应)
resume_file ──1:0..1──> resume   (resume.file_id)

job ──1:N──> application         (application.job_id)
candidate ──1:N──> application   (application.candidate_id)
application ──1:N──> application_stage_history

job + candidate ──1:1──> match_result  (唯一性由指纹/业务保证，当前无唯一约束)
job ──1:N──> ai_call             (可为空，JD 生成时尚未落库)
```

**关键设计说明**

1. **候选人去重**：`candidate.dedupe_key` 存邮箱或手机号归一后的值并加唯一索引；同一人上传多份简历时合并到同一 candidate，`resume_file` / `resume` 允许多条。
2. **重复上传不重复解析**：`resume_file.sha256` 唯一，同一文件再次上传直接复用已有解析结果。
3. **可解释匹配**：`match_result` 不只存总分，还存四个维度分、命中/缺失技能与 `detail` 明细——答辩时能逐条解释分数怎么来的。
4. **缓存不重复计费**：`match_result.fingerprint` = 职位版本 + 简历内容 hash；指纹一致直接复用，不再次调用大模型。
5. **状态可追溯**：任何状态变更都写 `application_stage_history`，看板的阶段停留时长从这里算，不依赖前端。

---

## 四、与 PRD 第 7 章的对照

| PRD 表 | PRD 要求 | 本项目落地 | 差异说明 |
|---|---|---|---|
| `jobs` | 7.2.1 | `job` | 补齐 department/location/headcount/薪资/must_have_skills；`skills` 用 JSON 存归一后的列表 |
| `candidates` | 7.2.2 | `candidate` | 拆出 `resume_file` / `resume` 两张表，避免把大 JSON 塞进候选人主表 |
| `applications` | 7.2.3 | `application` + `application_stage_history` | 增加来源渠道、阶段进入时间、流转历史（PRD 只给了状态字段，周期分析需要历史） |
| `ai_calls` | 7.2.4 | `ai_call` | 增加 feature（场景）、provider、duration_ms，便于按功能/厂商统计 |
| `companies` | 7.2.1 外键 `company_id` | **未建** | 当前为单公司部署，`company_id` 省略；做多租户时再加（阶段 7 之后） |

**PRD 隐含但尚未建的表**（按阶段计划后续补）

| 表 | 用途 | 计划阶段 |
|---|---|:--:|
| `interviews` | 面试安排与面试官 | 阶段 6 |
| `interview_feedback` | 面试评分与结论 | 阶段 6 |
| `notifications` | 站内通知/邮件发送记录 | 阶段 6 |
| `audit_logs` | 敏感数据访问审计（合规要求） | 阶段 7 |

---

## 五、怎么改这张表

1. 改字段：改 `backend/dbs/mysql/models/*.py` → 重新执行本文档生成脚本 → 开发态删掉 `backend/talentmatch.db` 让它重建（当前没有 Alembic，阶段性重建可接受）。
2. 想切回 MySQL：不设 `DATABASE_URL`，走 `env.yaml` 的 `MYSQL` 段即可；SQLite 与 MySQL 的差异只在 JSON 的存储实现，模型层无方言代码。
3. 新增表时：在 `models/` 加文件 → 在 `dbs/mysql/database.py` 的 `init_db()` 里导入 → 在 `tests/conftest.py` 里导入 → 在本脚本 `TABLE_META` 补中文名与用途。
