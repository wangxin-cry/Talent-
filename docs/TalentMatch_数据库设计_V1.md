# TalentMatch 数据库设计（V1）

> 配套文档：《TalentMatch_项目设计方案_V1.md》《TalentMatch_对话式交互与产品画面_V1.md》
> 本文是**从零设计**的完整数据模型：20 张表、6 个分组，逐表说明作用，逐字段说明含义。
> 阅读顺序建议：先看 §1 总览和关系图 → 再看 §3 你要实现的那几张表 → 最后看 §4 枚举与 §6 合规。

---

# 一、总览

## 1.1 表清单（20 张，6 组）

| 组 | # | 表名 | 中文名 | 作用一句话 | 建设阶段 |
|:--:|:--:|---|---|---|:--:|
| **A 账号与配置** | 1 | `company` | 公司 | 企业主体，单公司部署时只有 1 行，为多租户预留 | 一 |
| | 2 | `user` | 用户 | 平台账号与三角色（招聘专员/用人经理/管理员） | 一（二扩字段） |
| | 3 | `auth_token` | 认证令牌 | 邮箱验证 / 找回密码的一次性令牌，只存哈希 | 二 |
| | 4 | `llm_config` | 大模型配置 | 多厂商 API Key 与模型参数，支持 BYOK 与全局默认 | 一 |
| **B 招聘核心** | 5 | `skill` | 技能词表 | 技能标准名与别名，解决"K8s / Kubernetes"归一问题 | 一 |
| | 6 | `job` | 职位 | JD、技能要求、薪资、发布状态 | 一 |
| | 7 | `candidate` | 候选人 | 候选人档案，多份简历合并为一人 | 一 |
| | 8 | `resume_file` | 简历原始文件 | 文件元信息与解析状态；**文件本体存 MinIO** | 一 |
| | 9 | `resume` | 简历解析结果 | 结构化字段 + 字段置信度 | 一 |
| | 10 | `application` | 应聘记录 | 谁投了哪个职位、当前走到哪一步 | 一 |
| | 11 | `application_stage_history` | 状态流转历史 | 每次状态变更留痕，算阶段耗时 | 一 |
| **C 评估与面试** | 12 | `match_result` | 人岗匹配结果 | 可解释的评分、命中/缺失技能、理由 | 一 |
| | 13 | `interview` | 面试安排 | 面试轮次、时间、面试官 | 六 |
| | 14 | `interview_feedback` | 面试评估 | 面试官各维度打分与结论 | 六 |
| **D 流程与通知** | 15 | `notification` | 通知记录 | 站内信/邮件发送记录与状态 | 六 |
| **E 会话与 AI 可观测** | 16 | `chat_session` | 对话会话 | 对话式入口的会话（一个招聘任务一个） | 九½ |
| | 17 | `chat_message` | 对话消息 | 消息文本 + 结果卡片数据 | 九½ |
| | 18 | `agent_trace` | 编排轨迹 | 每个 Agent 每一步的执行记录（耗时/状态/降级） | 九 |
| | 19 | `ai_call` | AI 调用计量 | 每次 LLM 调用的 token 与费用 | 一 |
| **F 治理** | 20 | `audit_log` | 审计日志 | 敏感数据访问与关键操作留痕 | 一 |

> 阶段一一次建齐 13 张核心表（A/B/C 的 match_result + ai_call + audit_log），避免后期频繁改表；`interview*`、`notification`、`agent_trace`、`chat_*` 按对应阶段补建。
> **阶段二新增** `auth_token` 表，并给 `user` 补 `email_verified_at`、`token_version` 两个字段（支持邮箱验证与登出吊销）。

## 1.2 实体关系图

```
company 1──* user
company 1──* job
company 1──* candidate
company 1──* application
company 1──* ai_call / audit_log / notification / chat_session

user 1──* llm_config            (每用户每厂商一条)
user 1──* auth_token            (邮箱验证 / 找回密码令牌)
user 1──* job                   (created_by)
user 1──* candidate             (created_by)
user 1──* ai_call               (触发人)

job 1──* application
candidate 1──* application
application 1──* application_stage_history
application 1──* interview
interview 1──* interview_feedback

candidate 1──* resume_file      (同一人可多份简历)
resume_file 1──0..1 resume      (一次上传产出一份解析结果)
candidate 1──* resume

job 1──* match_result
candidate 1──* match_result
resume 1──* match_result        (参与计算的简历版本)

chat_session 1──* chat_message
chat_message 0..1──1 agent_trace (一条助手消息可对应一次编排)
agent_trace 1──* ai_call        (一次编排内可能多次 LLM 调用)
application 1──* notification
```

## 1.3 设计原则（8 条）

1. **主键用自增 BIGINT，不用 UUID**。单库单公司场景，自增更快、更省索引空间、调试友好；对外接口用 `id` 即可，不暴露内部结构。PRD 写 UUID 是为了分布式，当前不需要（见 §9 ADR-1）。
2. **简历拆三张表**：`resume_file`（原始文件）、`resume`（解析结果）、`candidate`（人）。一个人多份简历、一份简历多次解析版本都能容纳，不会把大 JSON 塞进候选人主表。
3. **匹配结果必须落库且可解释**：存四个维度分 + 命中/缺失技能 + 理由明细，而不是只存一个总分。否则"为什么他 87 分"永远答不出来。
4. **状态变更必须有历史**：`application_stage_history` 单独存，看板的阶段停留时长从这里算，不依赖前端。
5. **AI 的"流程"和"钱"分开记**：`agent_trace` 记编排每一步（谁跑的、多久、是否降级）；`ai_call` 记每次 LLM 调用（token、费用）。两者用 `trace_id` 关联。
6. **PII 加密 + hash 索引**：手机号、邮箱加密存储，同时存一份不可逆 hash 用于去重和精确查找——既不泄漏原文，又能查。
7. **逻辑外键 + 显式索引**：不建物理外键约束。原因：便于未来分库/迁移、避免误级联删数据；关系完整性由服务层保证（见 §9 ADR-2）。
8. **一次性建表 + 冗余字段**：`job.apply_count`、`application.match_score`、`application.stage_entered_at` 这类冗余是为了列表页和统计不必每次 JOIN 聚合。

---

# 二、命名与类型规范

## 2.1 命名规范

| 类别 | 规范 | 示例 |
|---|---|---|
| 表名 | 单数、小写下划线 | `job`、`resume_file`、`application_stage_history` |
| 字段 | 小写下划线 | `must_have_skills`、`years_experience` |
| 时间字段 | 事件用 `xxx_at`，系统维护用 `xxx_time` | `published_at`（业务事件）、`create_time`（系统写入） |
| 布尔字段 | `is_` / `has_` 开头 | `is_primary`、`is_deleted`、`cache_hit` |
| 金额字段 | 单位写在注释里 | `salary_min`（K/月）、`cost`（元） |
| 状态字段 | 统一叫 `status`，值用英文小写 | `status = 'published'` |
| 外键字段 | `xxx_id` | `job_id`、`candidate_id` |
| 加密字段 | 后缀 `_enc` | `phone_enc`、`email_enc` |
| 指纹/哈希 | 后缀 `_hash` 或 `sha256` | `email_hash`、`content_hash` |
| MinIO 桶名 | `talentmatch-{用途}` | `talentmatch-resume` |
| 对象键 | `{company_id}/{类型}/{yyyy}/{mm}/{uuid}.{ext}` | `1/resume/2026/11/xxx.pdf`（**不含姓名**） |

## 2.2 类型约定

| 语义 | MySQL | 开发态 SQLite | 说明 |
|---|---|---|---|
| 主键 | `BIGINT AUTO_INCREMENT` | `INTEGER` | 自增 |
| 短文本 | `VARCHAR(n)` | `VARCHAR(n)` | n 按实际长度给，别一律 255 |
| 长文本 | `TEXT` | `TEXT` | JD、简历原文、通知正文 |
| 结构化 | `JSON` | `JSON`（TEXT 存储） | 技能数组、评分明细、卡片数据 |
| 小数 | `DECIMAL(p,s)` | `NUMERIC` | **金额与分数禁用 FLOAT**，避免精度误差 |
| 布尔 | `BOOLEAN`（TINYINT） | `BOOLEAN` | |
| 时间 | `DATETIME` | `DATETIME` | 统一存 UTC，展示转 Asia/Shanghai |
| 哈希 | `CHAR(64)` | `CHAR(64)` | SHA-256 十六进制 |

## 2.3 通用字段

以下字段在多数表出现，后文不再重复解释：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | BIGINT PK | 自增主键 |
| `company_id` | BIGINT IDX | 所属公司（单公司部署恒为 1，多租户时用于隔离） |
| `create_time` | DATETIME | 记录创建时间（UTC） |
| `update_time` | DATETIME | 最后更新时间（UTC），每次写操作刷新 |

---

# 三、逐表设计

## 3.1 账号与配置

### 3.1.1 `company` —— 公司

**作用**：企业主体信息。单公司部署时只有一行，用于承载品牌（投递页 logo/主色）与企业级配置；为后期多租户预留隔离键。

**何时写/读**：初始化时写入 1 行；投递页渲染读品牌信息；所有业务表的 `company_id` 指向它。

**关键设计点**：
- `careers_slug` 是候选人投递页的路径标识（`/careers/{slug}`），必须唯一。
- `brand_color` 供投递页动态换色，实现"个性化投递页面"（PRD CE-01）。

| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|:--:|---|
| `id` | BIGINT | PK | | 主键 |
| `name` | VARCHAR(200) | NOT NULL | | 公司全称 |
| `short_name` | VARCHAR(50) | | NULL | 简称，用于界面标题 |
| `logo_url` | VARCHAR(500) | | NULL | 品牌 logo 地址 |
| `brand_color` | VARCHAR(20) | | NULL | 品牌主色（如 `#4f46e5`） |
| `careers_slug` | VARCHAR(100) | UQ | NULL | 投递页路径标识 |
| `industry` | VARCHAR(50) | | NULL | 所属行业 |
| `company_size` | VARCHAR(20) | | NULL | 规模区间（如 `100-499`） |
| `website` | VARCHAR(255) | | NULL | 官网 |
| `create_time` | DATETIME | NOT NULL | now | 创建时间 |
| `update_time` | DATETIME | | now | 更新时间 |

---

### 3.1.2 `user` —— 用户

**作用**：平台内部账号（招聘专员 / 用人经理 / 管理员）。**候选人不是这张表的用户**，候选人通过免登录投递页与进度查询接触系统。

**何时写/读**：注册、管理员建号；每次登录校验；每个接口鉴权取角色。

**关键设计点**：
- **`role` 是角色唯一来源**，不再设 `is_admin`（PRD 三角色；若沿用旧代码需保留 `is_admin` 并保证与 `role` 同步）。
- **登录失败锁定**：`login_fail_count` + `locked_until` 实现"5 次失败锁 15 分钟"（PRD §6.1.3）。也可放 Redis，落库更简单且可查。
- **`password` 只存 bcrypt 哈希**，永不存明文。
- **邮箱验证**：`email_verified_at` 为空即未验证。开发模式（`EMAIL_HOST` 为空）验证链接打印到后端控制台；启用 SMTP 后真实发信。未验证账号禁止登录。
- **令牌吊销**：`token_version` 写进 JWT 的 `ver` 声明；登出或重置密码时 +1，已签发 token 立即失效（`get_current_user` / `refresh` 都会比对）。

| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|:--:|---|
| `id` | BIGINT | PK | | 主键 |
| `company_id` | BIGINT | IDX | | 所属公司 |
| `name` | VARCHAR(50) | NOT NULL, UQ | | 登录名（用户名） |
| `email` | VARCHAR(255) | NOT NULL, UQ | | 邮箱，也用于通知与验证 |
| `password` | VARCHAR(255) | NOT NULL | | bcrypt 哈希 |
| `role` | VARCHAR(20) | NOT NULL, IDX | `recruiter` | `recruiter` / `manager` / `admin` |
| `phone` | VARCHAR(30) | | NULL | 内部人员手机 |
| `avatar_url` | VARCHAR(500) | | NULL | 头像 |
| `status` | VARCHAR(20) | NOT NULL | `active` | `active` / `disabled` |
| `email_verified_at` | DATETIME | | NULL | 邮箱验证通过时间；NULL 表示未验证，不可登录 |
| `last_login_at` | DATETIME | | NULL | 最后登录时间 |
| `login_fail_count` | INT | | 0 | 连续登录失败次数 |
| `locked_until` | DATETIME | | NULL | 账号锁定到期时间 |
| `token_version` | INT | NOT NULL | 0 | 令牌版本；登出 / 改密时 +1，旧 JWT 立即失效 |
| `create_time` | DATETIME | NOT NULL | now | 创建时间 |
| `update_time` | DATETIME | | now | 更新时间 |

**索引**：`UQ(name)`、`UQ(email)`、`IDX(company_id, role)`、`IDX(status)`

---

### 3.1.3 `auth_token` —— 认证令牌

**作用**：承载"邮箱验证"与"找回密码"两类一次性令牌，服务端只存哈希，不存明文。

**何时写/读**：注册成功、重发验证时写入；用户点击链接时读取并标记已用；忘记密码时签发；重置密码时消费。

**关键设计点**：
- **只存哈希**：`token_hash = sha256(明文)`，明文只出现在邮件或开发控制台，即使库泄漏也无法复用链接。
- **一次性**：`used_at` 非空即作废；同一用户签发新令牌时，旧令牌全部置为已用，保证"最新链接唯一有效"。
- **分用途隔离**：`purpose = verify_email / reset_password`，两类令牌不可互相冒用。
- **有效期**：邮箱验证 24 小时（`EMAIL_VERIFY_EXPIRE_HOURS`），重置密码 30 分钟，均由 `expires_at` 控制。

| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|:--:|---|
| `id` | BIGINT | PK | | 主键 |
| `user_id` | BIGINT | IDX, NOT NULL | | 所属用户 |
| `token_hash` | VARCHAR(64) | NOT NULL, UQ | | 明文令牌的 SHA-256 十六进制 |
| `purpose` | VARCHAR(30) | NOT NULL | | `verify_email` / `reset_password` |
| `expires_at` | DATETIME | NOT NULL | | 过期时间 |
| `used_at` | DATETIME | | NULL | 使用时间；非空表示已作废 |
| `create_time` | DATETIME | NOT NULL | now | 创建时间 |

**索引**：`UQ(token_hash)`、`IDX(user_id, purpose)`

---

### 3.1.4 `llm_config` —— 大模型配置

**作用**：多厂商 LLM 的接入配置。既支持**平台全局默认**（管理员维护），也支持**用户自带 Key（BYOK）**。

**何时写/读**：管理员在成本/设置页维护全局；用户可在个人设置填自己的 Key；每次调 LLM 前按"用户配置 → 全局配置 → 环境变量"优先级取一份生效配置。

**关键设计点**：
- **API Key 加密存储**（Fernet），密钥独立于 JWT 密钥，避免 JWT 轮换牵连。
- `user_id` 为空 + `scope='global'` 表示全局配置；有 `user_id` 表示个人配置。
- `is_active` 控制同一 `(scope, provider)` 下只有一个生效。

| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|:--:|---|
| `id` | BIGINT | PK | | 主键 |
| `user_id` | BIGINT | IDX | NULL | 所属用户；NULL 表示全局配置 |
| `scope` | VARCHAR(20) | NOT NULL | `user` | `user` 个人 / `global` 全局 |
| `provider` | VARCHAR(50) | NOT NULL | | 厂商标识：`zhipu` / `deepseek` / `openai` |
| `base_url` | VARCHAR(255) | | NULL | OpenAI 兼容接口地址 |
| `api_key_enc` | TEXT | NOT NULL | | 加密后的 API Key |
| `chat_model` | VARCHAR(100) | | NULL | 对话模型名 |
| `embedding_model` | VARCHAR(100) | | NULL | 向量模型名（可空） |
| `temperature` | DECIMAL(3,2) | | 0.70 | 采样温度 |
| `max_tokens` | INT | | 4096 | 单次最大输出 token |
| `is_active` | BOOLEAN | NOT NULL | 0 | 是否当前生效 |
| `create_time` | DATETIME | NOT NULL | now | 创建时间 |
| `update_time` | DATETIME | | now | 更新时间 |

**约束**：`UQ(scope, user_id, provider)`

---

## 3.2 招聘核心

### 3.2.1 `skill` —— 技能词表

**作用**：技能标准名与别名的映射表。**这是匹配准确率的地基**——"K8s"、"kubernetes"、"K8S" 必须归一到同一个 `skill_id`，否则简历写 K8s、JD 写 Kubernetes 就会漏匹配。

**何时写/读**：系统初始化导入 200+ 条；解析简历、生成 JD、匹配时都查它做归一。

**关键设计点**：
- `aliases` 用 JSON 存别名数组，查表时先精确匹配 `name`，再遍历别名。
- `category` 用于分类展示与加权（如"软技能"权重低于"编程语言"）。
- `parent_id` 支持层级（Java → Spring），当前可先不用。

| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|:--:|---|
| `id` | BIGINT | PK | | 主键 |
| `name` | VARCHAR(100) | NOT NULL, UQ | | 标准名（如 `Kubernetes`） |
| `display_name` | VARCHAR(100) | | NULL | 展示名（中文名如 `容器编排`） |
| `aliases` | JSON | | `[]` | 别名数组（`["K8s","k8s","kube"]`） |
| `category` | VARCHAR(50) | IDX | NULL | `language` / `framework` / `database` / `middleware` / `tool` / `soft` |
| `parent_id` | BIGINT | | NULL | 上级技能 |
| `is_active` | BOOLEAN | NOT NULL | 1 | 是否启用 |
| `create_time` | DATETIME | NOT NULL | now | 创建时间 |

---

### 3.2.2 `job` —— 职位

**作用**：招聘职位。整条招聘链路的起点——有职位才有应聘、匹配、面试、看板。

**何时写/读**：招聘专员创建/编辑；用人经理审批；发布后出现在在招列表与投递页；匹配与面试都读它的快照。

**关键设计点**：
- **`jd_version` 每次实质修改 +1**：匹配缓存指纹依赖它。改了 JD 就必须重算匹配，否则会拿旧分数骗人。
- **`skills` 存归一后的 `skill_id` 数组**（不是自由文本），匹配才能按 id 比对。
- **`must_have_skills` 单独存**：必备技能缺失要重罚（见算法设计），不能和加分技能混在一起。
- `apply_count` 是冗余计数，列表页直接显示，不用每次 COUNT。

| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|:--:|---|
| `id` | BIGINT | PK | | 主键 |
| `company_id` | BIGINT | IDX | | 所属公司 |
| `title` | VARCHAR(200) | NOT NULL, IDX | | 职位名称 |
| `department` | VARCHAR(100) | IDX | NULL | 所属部门 |
| `location` | VARCHAR(100) | | NULL | 工作地点 |
| `work_mode` | VARCHAR(20) | | NULL | `onsite` / `hybrid` / `remote` |
| `employment_type` | VARCHAR(20) | | `fulltime` | `fulltime` / `intern` / `parttime` |
| `headcount` | INT | | 1 | 招聘人数 |
| `description` | TEXT | | NULL | 职位描述（职责） |
| `requirements` | TEXT | | NULL | 任职要求 |
| `skills` | JSON | | `[]` | 技能要求（归一后的 `skill_id` 数组） |
| `must_have_skills` | JSON | | `[]` | 必备技能子集（`skill_id` 数组） |
| `min_years` | DECIMAL(4,1) | | NULL | 经验要求（年） |
| `education_level` | VARCHAR(20) | | NULL | 最低学历：`college`/`bachelor`/`master`/`phd` |
| `salary_min` | INT | | NULL | 月薪下限（K） |
| `salary_max` | INT | | NULL | 月薪上限（K） |
| `status` | VARCHAR(20) | NOT NULL, IDX | `draft` | `draft`/`pending`/`published`/`closed`/`archived` |
| `jd_source` | VARCHAR(20) | | `manual` | `manual` 手写 / `ai` AI 生成后修改 |
| `jd_version` | INT | NOT NULL | 1 | JD 版本号（匹配缓存键） |
| `published_at` | DATETIME | | NULL | 发布时间 |
| `closed_at` | DATETIME | | NULL | 关闭时间 |
| `approved_by` | BIGINT | | NULL | 审批人（用人经理） |
| `approved_at` | DATETIME | | NULL | 审批时间 |
| `reject_reason` | TEXT | | NULL | 审批驳回原因 |
| `apply_count` | INT | | 0 | 应聘人数（冗余计数） |
| `created_by` | BIGINT | IDX | NULL | 创建人 |
| `create_time` | DATETIME | NOT NULL | now | 创建时间 |
| `update_time` | DATETIME | | now | 更新时间 |

**索引**：`IDX(company_id, status, update_time)`、`IDX(title)`、`IDX(published_at)`

---

### 3.2.3 `candidate` —— 候选人

**作用**：候选人档案，是"人"的维度。同一候选人的多份简历（不同格式、不同时间）都合并到这里。

**何时写/读**：简历上传解析后写入或合并；人才库检索、匹配、投递查它。

**关键设计点**：
- **`dedupe_key` 是去重的唯一依据**：优先邮箱 hash，其次手机 hash，都没有才退化到"姓名 + 手机后 4 位 + 最近公司"。**绝不能只按姓名去重**（同名同姓太常见）。
- **PII 加密**：`phone_enc`/`email_enc` 存密文；同时存 `phone_hash`/`email_hash` 供查找去重——查得到、但看不到明文。
- **`is_deleted` + `deleted_at`**：满足 PIPL"删除权"，逻辑删除 PII 而保留审计痕迹。
- **`resume_text` 冗余**最近一份简历纯文本，匹配时不必再 JOIN `resume` 取原文。

| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|:--:|---|
| `id` | BIGINT | PK | | 主键 |
| `company_id` | BIGINT | IDX | | 所属公司 |
| `name` | VARCHAR(100) | NOT NULL, IDX | | 姓名 |
| `phone_enc` | VARCHAR(255) | | NULL | 手机号（加密） |
| `phone_hash` | CHAR(64) | IDX | NULL | 归一后手机号 hash（去重用） |
| `email_enc` | VARCHAR(255) | | NULL | 邮箱（加密） |
| `email_hash` | CHAR(64) | IDX | NULL | 邮箱 hash（去重用） |
| `dedupe_key` | VARCHAR(64) | UQ | NULL | 去重键 |
| `city` | VARCHAR(50) | | NULL | 所在城市 |
| `education_level` | VARCHAR(20) | | NULL | 最高学历 |
| `school` | VARCHAR(100) | | NULL | 毕业院校 |
| `major` | VARCHAR(100) | | NULL | 专业 |
| `years_experience` | DECIMAL(4,1) | | NULL | 工作年限 |
| `current_company` | VARCHAR(200) | | NULL | 最近公司 |
| `current_title` | VARCHAR(100) | | NULL | 最近职位 |
| `expected_salary_min` | INT | | NULL | 期望月薪下限（K） |
| `expected_salary_max` | INT | | NULL | 期望月薪上限（K） |
| `skills` | JSON | | `[]` | 技能标签（`[{skill_id,name,years,source}]`） |
| `tags` | JSON | | `[]` | HR 自定义标签 |
| `source_channel` | VARCHAR(30) | IDX | NULL | `website`/`referral`/`headhunter`/`other` |
| `source_detail` | VARCHAR(200) | | NULL | 来源细节（如猎头公司名） |
| `resume_text` | TEXT | | NULL | 主简历纯文本（匹配用） |
| `is_deleted` | BOOLEAN | NOT NULL | 0 | 是否已删除（PIPL） |
| `deleted_at` | DATETIME | | NULL | 删除时间 |
| `created_by` | BIGINT | | NULL | 录入人 |
| `create_time` | DATETIME | NOT NULL | now | 创建时间 |
| `update_time` | DATETIME | | now | 更新时间 |

**索引**：`UQ(dedupe_key)`、`IDX(company_id, create_time)`、`IDX(email_hash)`、`IDX(phone_hash)`、`IDX(name)`

---

### 3.2.4 `resume_file` —— 简历原始文件

**作用**：记录上传的每个文件（PDF/DOCX/图片）及其解析状态，是"文件"的维度。**文件本体存 MinIO 对象存储，本表只存元信息与对象键**（详见 §3.7）。

**何时写/读**：上传时先落 MinIO 再写本表；解析任务读取；解析结果回写状态；失败可重试；下载/预览时据此生成预签名 URL。

**关键设计点**：
- **文件不进数据库、也不放本地磁盘**：`bucket` + `object_key` 指向 MinIO 对象；对象键用 UUID 命名、**不含姓名等 PII**。
- **`sha256` 唯一**：同一文件重复上传直接命中已有记录，**不再重复上传对象、不重复解析、不重复花钱**。
- **`source` 区分两个入口**：`upload`（HR 批量上传）、`careers_page`（候选人自助投递）、`email`（邮件导入）。两个入口汇入同一条处理链。
- **`applied_job_id`**：若这份简历是冲着某个职位来的，记下职位 → 解析成功后可直接生成应聘记录；为空则只进人才库。
- **状态机**：`pending → parsing → success | failed`，失败可 `retry`。

| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|:--:|---|
| `id` | BIGINT | PK | | 主键 |
| `company_id` | BIGINT | IDX | | 所属公司 |
| `candidate_id` | BIGINT | IDX | NULL | 归属候选人（解析成功前为空） |
| `original_name` | VARCHAR(255) | NOT NULL | | 上传时的原始文件名 |
| `bucket` | VARCHAR(100) | | NULL | MinIO 桶名（如 `talentmatch-resume`） |
| `object_key` | VARCHAR(500) | IDX | NULL | 对象键（UUID 命名，不含姓名），如 `1/resume/2026/11/uuid.pdf` |
| `etag` | VARCHAR(64) | | NULL | 对象 ETag（上传完整性校验） |
| `ext` | VARCHAR(10) | | NULL | 扩展名 |
| `mime` | VARCHAR(100) | | NULL | MIME 类型 |
| `size_bytes` | INT | | NULL | 文件大小 |
| `sha256` | CHAR(64) | UQ | NULL | 内容指纹（防重复解析） |
| `source` | VARCHAR(20) | NOT NULL | `upload` | `upload`/`careers_page`/`email` |
| `applied_job_id` | BIGINT | IDX | NULL | 投递目标职位（可空） |
| `status` | VARCHAR(20) | NOT NULL, IDX | `pending` | `pending`/`parsing`/`success`/`failed` |
| `parser` | VARCHAR(30) | | NULL | 实际使用的解析器 |
| `error_reason` | TEXT | | NULL | 失败原因（给 HR 看的一句话） |
| `retry_count` | INT | | 0 | 重试次数 |
| `uploaded_by` | BIGINT | | NULL | 上传人（自助投递时为空） |
| `create_time` | DATETIME | NOT NULL | now | 上传时间 |
| `parsed_time` | DATETIME | | NULL | 解析完成时间 |

**索引**：`UQ(sha256)`、`IDX(candidate_id)`、`IDX(status)`、`IDX(company_id, create_time)`

---

### 3.2.5 `resume` —— 简历解析结果

**作用**：保存从文件解析出的结构化内容与字段置信度，是"内容"的维度。

**何时写/读**：解析成功后写入；校对页读取；匹配时取结构化字段；面试题生成时取项目经历。

**关键设计点**：
- **`structured` 存完整结构化 JSON**（姓名/教育/工作/项目/技能/证书），前端校对页直接渲染。
- **`field_confidence` 存字段级置信度**，低置信字段标黄提示人工校对——这是"人机协作"的关键，不是让 AI 一把梭。
- **`content_hash`**：简历内容指纹，与 `job.jd_version` 一起构成匹配缓存键。
- **`version`**：同一文件可多次解析（换模型/重试），保留版本便于对比。

| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|:--:|---|
| `id` | BIGINT | PK | | 主键 |
| `candidate_id` | BIGINT | NOT NULL, IDX | | 归属候选人 |
| `file_id` | BIGINT | IDX | NULL | 来源文件 |
| `structured` | JSON | | `{}` | 结构化内容 |
| `field_confidence` | JSON | | `{}` | 字段置信度 `{field: 0~1}` |
| `plain_text` | TEXT | | NULL | 简历纯文本 |
| `parser_meta` | JSON | | `{}` | `{parser, pages, duration_ms}` |
| `content_hash` | CHAR(64) | IDX | NULL | 内容指纹（匹配缓存键） |
| `is_primary` | BOOLEAN | NOT NULL | 0 | 是否该候选人的主简历 |
| `version` | INT | NOT NULL | 1 | 解析版本 |
| `create_time` | DATETIME | NOT NULL | now | 入库时间 |

**索引**：`IDX(candidate_id, is_primary)`、`IDX(content_hash)`

---

### 3.2.6 `application` —— 应聘记录

**作用**：连接"职位"与"候选人"的应聘关系，承载招聘流程状态。**看板、漏斗、周期分析、通知的全部数据源**。

**何时写/读**：候选人投递或 HR 手动关联时创建；拖看板改状态；看板与漏斗统计读它。

**关键设计点**：
- **`UNIQUE(job_id, candidate_id)`**：同一个人对同一职位只有一条应聘记录，重复投递是更新而不是新建。
- **`stage_entered_at` 是关键**：算"在当前阶段停留多久"、SLA 超时、周期分析都靠它。每次状态变更必须刷新，忘了就全错。
- **`match_score` 快照**：投递时的分数存下来，之后重算匹配不影响历史记录。
- **注意与人才库的区别**：只在人才库里的候选人**没有** application 记录；只有明确投了某职位才有。

| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|:--:|---|
| `id` | BIGINT | PK | | 主键 |
| `company_id` | BIGINT | IDX | | 所属公司 |
| `job_id` | BIGINT | NOT NULL, IDX | | 应聘职位 |
| `candidate_id` | BIGINT | NOT NULL, IDX | | 应聘候选人 |
| `status` | VARCHAR(20) | NOT NULL, IDX | `new` | `new`/`screening`/`interview`/`offer`/`hired`/`rejected` |
| `source` | VARCHAR(30) | | NULL | 本次投递来源渠道 |
| `match_score` | DECIMAL(5,2) | | NULL | 投递时匹配分（快照） |
| `applied_at` | DATETIME | NOT NULL | now | 投递时间 |
| `stage_entered_at` | DATETIME | NOT NULL | now | 进入当前阶段的时间 |
| `rejected_reason` | TEXT | | NULL | 淘汰原因（`rejected` 时必填） |
| `rejected_by` | BIGINT | | NULL | 淘汰操作人 |
| `offer_salary` | INT | | NULL | Offer 月薪（K） |
| `offer_accepted_at` | DATETIME | | NULL | 接受 Offer 时间 |
| `hired_at` | DATETIME | | NULL | 入职时间 |
| `created_by` | BIGINT | | NULL | 创建人（自助投递为空） |
| `create_time` | DATETIME | NOT NULL | now | 创建时间 |
| `update_time` | DATETIME | | now | 更新时间 |

**索引**：`UQ(job_id, candidate_id)`、`IDX(job_id, status)`、`IDX(candidate_id)`、`IDX(company_id, status)`、`IDX(stage_entered_at)`、`IDX(applied_at)`

---

### 3.2.7 `application_stage_history` —— 状态流转历史

**作用**：记录每一次状态变更（谁、何时、从哪到哪、为什么）。前端时间线、阶段停留时长、SLA 统计都依赖它。

**何时写/读**：每次状态流转写一条（**只增不改**）；候选人详情页展示时间线；周期分析算各阶段平均耗时。

**关键设计点**：
- **只追加，不更新不删除**——这是审计级数据，改了就没法追溯。
- `from_status` 为空表示首次进入流程。
- `duration_in_prev_status` 冗余上一阶段停留秒数，统计时不必再算差值（也可实时算，此字段为加速）。

| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|:--:|---|
| `id` | BIGINT | PK | | 主键 |
| `application_id` | BIGINT | NOT NULL, IDX | | 所属应聘记录 |
| `from_status` | VARCHAR(20) | | NULL | 变更前状态（首次为空） |
| `to_status` | VARCHAR(20) | NOT NULL, IDX | | 变更后状态 |
| `operator_id` | BIGINT | | NULL | 操作人（系统触发为空） |
| `note` | TEXT | | NULL | 备注（如淘汰原因） |
| `duration_in_prev_status` | INT | | NULL | 在上一阶段停留秒数（冗余） |
| `create_time` | DATETIME | NOT NULL | now | 变更时间 |

**索引**：`IDX(application_id, create_time)`、`IDX(to_status)`

---

## 3.3 评估与面试

### 3.3.1 `match_result` —— 人岗匹配结果

**作用**：保存"某职位 × 某候选人"的可解释匹配结论：总分、四个维度分、命中/缺失技能、理由明细。**这是产品最核心的价值数据**。

**何时写/读**：点"智能匹配"时批量计算写入；排名页读取；面试题生成读取其"缺口"。

**关键设计点**：
- **四个维度分必须分开存**：只存总分等于放弃可解释性，答辩第一个问题就答不上来。
- **`fingerprint` 是缓存键**：`job.jd_version + resume.content_hash + 打分权重版本`。指纹没变→直接复用，不重复调 LLM、不重复计费。
- **`scope` 区分匹配范围**：`application`（只匹配投递了该职位的人）vs `talent_pool`（匹配全人才库）。这两个场景结果不同，必须分开存。
- **`reason_source` 记录理由来源**：`llm` 还是 `template`（降级），便于统计降级率。

| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|:--:|---|
| `id` | BIGINT | PK | | 主键 |
| `company_id` | BIGINT | IDX | | 所属公司 |
| `job_id` | BIGINT | NOT NULL, IDX | | 职位 |
| `candidate_id` | BIGINT | NOT NULL, IDX | | 候选人 |
| `resume_id` | BIGINT | | NULL | 参与计算的简历版本 |
| `scope` | VARCHAR(20) | NOT NULL | `application` | `application`/`talent_pool` |
| `score` | DECIMAL(5,2) | NOT NULL | | 综合分 0~100 |
| `skill_score` | DECIMAL(5,4) | | NULL | 技能维度 0~1 |
| `exp_score` | DECIMAL(5,4) | | NULL | 经验维度 0~1 |
| `edu_score` | DECIMAL(5,4) | | NULL | 学历维度 0~1 |
| `other_score` | DECIMAL(5,4) | | NULL | 其他维度 0~1 |
| `matched_skills` | JSON | | `[]` | 命中的技能 |
| `missing_skills` | JSON | | `[]` | 缺失的技能 |
| `must_have_hit` | INT | | 0 | 必备技能命中数 |
| `must_have_total` | INT | | 0 | 必备技能总数 |
| `summary` | VARCHAR(500) | | NULL | 一句话结论（列表展示） |
| `detail` | JSON | | `{}` | 完整理由明细（各维度扣分原因、经验差等） |
| `reason_source` | VARCHAR(20) | | NULL | `llm`/`template` |
| `fingerprint` | CHAR(64) | IDX | NULL | 缓存指纹 |
| `created_by` | BIGINT | | NULL | 触发人 |
| `create_time` | DATETIME | NOT NULL | now | 计算时间 |

**索引**：`IDX(job_id, score)`、`IDX(job_id, candidate_id, scope)`、`IDX(fingerprint)`、`IDX(company_id, create_time)`

---

### 3.3.2 `interview` —— 面试安排

**作用**：记录一次面试的时间、形式、面试官、状态。支撑面试安排与日历邀请（ICS）。

**何时写/读**：HR 安排面试时写入；面试官查自己的日程；发出邀请时生成 ICS。

**关键设计点**：
- `round` 区分第几轮（一面/二面/终面），同一应聘记录可多轮。
- `interviewer_ids` 用 JSON 数组存面试官，避免再建关联表（面试官通常 1~3 人）。
- 冲突检测：同一面试官同一时间段不能有两场（应用层校验）。

| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|:--:|---|
| `id` | BIGINT | PK | | 主键 |
| `company_id` | BIGINT | IDX | | 所属公司 |
| `application_id` | BIGINT | NOT NULL, IDX | | 所属应聘记录 |
| `round` | INT | NOT NULL | 1 | 面试轮次 |
| `type` | VARCHAR(20) | | `video` | `phone`/`video`/`onsite` |
| `scheduled_start` | DATETIME | IDX | NULL | 开始时间 |
| `scheduled_end` | DATETIME | | NULL | 结束时间 |
| `duration_min` | INT | | 60 | 时长（分钟） |
| `location` | VARCHAR(255) | | NULL | 地点或会议链接 |
| `interviewer_ids` | JSON | | `[]` | 面试官 user id 数组 |
| `status` | VARCHAR(20) | NOT NULL, IDX | `scheduled` | `scheduled`/`done`/`cancelled`/`no_show` |
| `ics_sent` | BOOLEAN | | 0 | 是否已发日历邀请 |
| `notes` | TEXT | | NULL | 备注 |
| `created_by` | BIGINT | | NULL | 安排人 |
| `create_time` | DATETIME | NOT NULL | now | 创建时间 |
| `update_time` | DATETIME | | now | 更新时间 |

**索引**：`IDX(application_id, round)`、`IDX(scheduled_start)`、`IDX(company_id, status)`

---

### 3.3.3 `interview_feedback` —— 面试评估

**作用**：面试官提交的结构化评估（各维度打分 + 结论 + 文字评价）。

**何时写/读**：面试后由面试官填写；候选人详情页汇总展示；决策参考。

**关键设计点**：
- `dims` 存维度分 JSON（技术深度/沟通/主动性/文化匹配），模板可配。
- 一个面试官对一场面试只能提交一次（`UNIQUE(interview_id, interviewer_id)`）。

| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|:--:|---|
| `id` | BIGINT | PK | | 主键 |
| `interview_id` | BIGINT | NOT NULL, IDX | | 所属面试 |
| `interviewer_id` | BIGINT | NOT NULL, IDX | | 面试官 |
| `dims` | JSON | | `{}` | 维度分 `{技术深度:4,...}` |
| `overall_score` | DECIMAL(3,1) | | NULL | 综合评分 1~5 |
| `conclusion` | VARCHAR(20) | | NULL | `pass`/`reject`/`hold` |
| `strengths` | TEXT | | NULL | 优点 |
| `concerns` | TEXT | | NULL | 顾虑 |
| `submitted_at` | DATETIME | | NULL | 提交时间 |
| `create_time` | DATETIME | NOT NULL | now | 创建时间 |

**约束**：`UQ(interview_id, interviewer_id)`

---

## 3.4 流程与通知

### 3.4.1 `notification` —— 通知记录

**作用**：所有对外/对内通知的发送记录（站内信、邮件、短信、webhook），含状态与失败原因。

**何时写/读**：状态变更触发时写入；通知中心列表；失败重发；候选人收到的邮件也在这里留痕。

**关键设计点**：
- **`channel` 抽象渠道**：`inapp`（站内信）/`email`/`sms`/`webhook`。开发期可只用 `inapp` + `console`，投产再接邮件。
- **发送失败不影响业务**：状态流转成功即算成功，通知失败单独记 `failed` 可重发。
- `to_addr` 存脱敏后的地址（如 `z***@example.com`），避免通知表成为 PII 泄漏点。

| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|:--:|---|
| `id` | BIGINT | PK | | 主键 |
| `company_id` | BIGINT | IDX | | 所属公司 |
| `user_id` | BIGINT | IDX | NULL | 接收人（站内信） |
| `candidate_id` | BIGINT | IDX | NULL | 相关候选人 |
| `application_id` | BIGINT | IDX | NULL | 相关应聘记录 |
| `channel` | VARCHAR(20) | NOT NULL | `inapp` | `inapp`/`email`/`sms`/`webhook` |
| `template` | VARCHAR(50) | NOT NULL | | `resume_received`/`interview_invite`/`offer`/`rejected`/`status_update` |
| `subject` | VARCHAR(200) | | NULL | 标题 |
| `body` | TEXT | | NULL | 正文 |
| `to_addr` | VARCHAR(255) | | NULL | 收件地址（脱敏） |
| `status` | VARCHAR(20) | NOT NULL, IDX | `pending` | `pending`/`sent`/`failed`/`read` |
| `error_reason` | TEXT | | NULL | 失败原因 |
| `sent_at` | DATETIME | | NULL | 发送时间 |
| `read_at` | DATETIME | | NULL | 已读时间 |
| `create_time` | DATETIME | NOT NULL | now | 创建时间 |

**索引**：`IDX(user_id, status, create_time)`、`IDX(application_id)`、`IDX(company_id, create_time)`

---

## 3.5 会话与 AI 可观测

### 3.5.1 `chat_session` —— 对话会话

**作用**：对话式入口的会话容器。一个招聘任务（如"Python 岗筛选"）对应一个会话，可切换回看。

**何时写/读**：用户新建会话/发首条消息时创建；左栏会话列表读取；切换会话时加载历史消息。

**关键设计点**：
- **`context_job_id` / `context_candidate_id`**：保存"当前上下文"。没有它，用户说"匹配一下"系统就不知道匹配哪个职位——这是上下文推断的落点。
- `last_message_at` 用于会话列表排序。

| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|:--:|---|
| `id` | BIGINT | PK | | 主键 |
| `company_id` | BIGINT | IDX | | 所属公司 |
| `user_id` | BIGINT | NOT NULL, IDX | | 会话归属用户 |
| `title` | VARCHAR(100) | | NULL | 会话标题（可自动生成） |
| `context_job_id` | BIGINT | | NULL | 当前上下文职位 |
| `context_candidate_id` | BIGINT | | NULL | 当前上下文候选人 |
| `last_message_at` | DATETIME | IDX | NULL | 最后消息时间 |
| `create_time` | DATETIME | NOT NULL | now | 创建时间 |
| `update_time` | DATETIME | | now | 更新时间 |

**索引**：`IDX(user_id, last_message_at)`

---

### 3.5.2 `chat_message` —— 对话消息

**作用**：持久化对话内容与结果卡片，支持刷新后回看、会话切换。

**何时写/读**：每轮对话写入；打开会话加载；卡片渲染读 `card_data`。

**关键设计点**：
- **`card_type` + `card_data`**：把"结果卡片"结构化存下来（排名/面试题/确认/图表），不是存 HTML。这样前端换 UI 也能重新渲染。
- `intent` 记录该轮识别出的意图，用于复盘"识别错在哪"。
- `trace_id` 关联编排轨迹，点开卡片能看"这步跑了多久、花了多少钱"。

| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|:--:|---|
| `id` | BIGINT | PK | | 主键 |
| `session_id` | BIGINT | NOT NULL, IDX | | 所属会话 |
| `role` | VARCHAR(20) | NOT NULL | | `user`/`assistant`/`system` |
| `content` | TEXT | | NULL | 文本内容 |
| `card_type` | VARCHAR(30) | | NULL | `upload`/`parse_result`/`match_rank`/`interview`/`confirm`/`chart` |
| `card_data` | JSON | | `{}` | 卡片结构化数据 |
| `intent` | VARCHAR(50) | | NULL | 识别出的意图 |
| `trace_id` | VARCHAR(64) | IDX | NULL | 关联编排轨迹 |
| `tokens` | INT | | 0 | 本轮消耗 token |
| `cost` | DECIMAL(10,6) | | 0 | 本轮费用（元） |
| `create_time` | DATETIME | NOT NULL | now | 创建时间 |

**索引**：`IDX(session_id, create_time)`、`IDX(trace_id)`

---

### 3.5.3 `agent_trace` —— 编排轨迹

**作用**：记录一次编排中**每个 Agent 每一步**的执行情况：谁跑的、多久、是否降级、调了哪些工具、花了多少 token。

**何时写/读**：每次多 Agent 编排每步写一条；前端"编排轨迹"面板读取；排查问题与答辩演示用。

**关键设计点**：
- **一次编排共享一个 `trace_id`**，多条记录 `step_no` 递增。
- **只存摘要不存全文**：`input_summary` / `output_summary` 存字段摘要，避免简历全文进轨迹表（隐私 + 体积）。
- **`degraded` 标记降级**：哪个 Agent 挂了用兜底结果，一目了然。
- 与 `ai_call` 分工：trace 记"流程步骤"，ai_call 记"每次模型调用"。一个 step 可能调 0~N 次模型。

| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|:--:|---|
| `id` | BIGINT | PK | | 主键 |
| `trace_id` | VARCHAR(64) | NOT NULL, IDX | | 一次编排的共享 id |
| `session_id` | BIGINT | IDX | NULL | 来源会话（页面触发时为空） |
| `step_no` | INT | NOT NULL | | 步骤序号 |
| `agent` | VARCHAR(50) | NOT NULL, IDX | | `Manager`/`JDWriter`/`ResumeParser`/`MatchEngine`/`InterviewAssistant`/`WorkflowAuto`/`Analytics` |
| `parent_step` | INT | | NULL | 父步骤（子任务归属） |
| `intent` | VARCHAR(50) | | NULL | 本次编排意图 |
| `input_summary` | JSON | | `{}` | 输入摘要（不含全文） |
| `input_hash` | CHAR(64) | | NULL | 输入指纹 |
| `output_summary` | JSON | | `{}` | 输出摘要 |
| `status` | VARCHAR(20) | NOT NULL | `success` | `success`/`failed`/`timeout`/`skipped`/`degraded` |
| `degraded` | BOOLEAN | NOT NULL | 0 | 是否降级 |
| `error_reason` | TEXT | | NULL | 失败原因 |
| `duration_ms` | INT | | NULL | 耗时（毫秒） |
| `tokens_in` | INT | | 0 | 输入 token |
| `tokens_out` | INT | | 0 | 输出 token |
| `cost` | DECIMAL(10,6) | | 0 | 本步费用（元） |
| `tool_calls` | JSON | | `[]` | 本步调用的工具列表 |
| `create_time` | DATETIME | NOT NULL | now | 记录时间 |

**索引**：`IDX(trace_id, step_no)`、`IDX(agent, create_time)`、`IDX(create_time)`

---

### 3.5.4 `ai_call` —— AI 调用计量

**作用**：每次 LLM 调用的明细账：用哪个模型、输入输出 token、费用、耗时、是否缓存命中。**成本控制与 CC-01~03 的数据基础**。

**何时写/读**：每次调模型后写入；成本页按职位/功能/时间聚合；预算检查读当月累计。

**关键设计点**：
- **`cache_hit` 单独记**：缓存命中时也写一条（cost=0），才能统计"省了多少钱"。
- **`feature` 按场景分类**：解析/匹配理由/JD 生成/面试题/洞察，成本分析才能看出钱花在哪。
- **`trace_id`** 关联到编排步骤，能回答"这次一键评估一共花了多少"。
- 金额用 `DECIMAL(10,6)`，避免小数累加误差。

| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|:--:|---|
| `id` | BIGINT | PK | | 主键 |
| `company_id` | BIGINT | IDX | | 所属公司 |
| `user_id` | BIGINT | IDX | NULL | 触发人 |
| `job_id` | BIGINT | IDX | NULL | 关联职位 |
| `candidate_id` | BIGINT | | NULL | 关联候选人 |
| `feature` | VARCHAR(50) | NOT NULL, IDX | | `resume_parse`/`jd_generate`/`match_explain`/`interview_generate`/`analytics_insight` |
| `agent` | VARCHAR(50) | | NULL | 哪个 Agent 触发的 |
| `provider` | VARCHAR(50) | | NULL | 厂商 |
| `model` | VARCHAR(100) | | NULL | 模型名 |
| `input_tokens` | INT | | 0 | 输入 token |
| `output_tokens` | INT | | 0 | 输出 token |
| `total_tokens` | INT | | 0 | 合计 token |
| `cost` | DECIMAL(10,6) | | 0 | 费用（元） |
| `currency` | VARCHAR(10) | | `CNY` | 币种 |
| `duration_ms` | INT | | NULL | 耗时 |
| `cache_hit` | BOOLEAN | NOT NULL | 0 | 是否缓存命中 |
| `status` | VARCHAR(20) | | `success` | `success`/`failed` |
| `error_reason` | TEXT | | NULL | 失败原因 |
| `trace_id` | VARCHAR(64) | IDX | NULL | 关联编排轨迹 |
| `create_time` | DATETIME | NOT NULL, IDX | now | 调用时间 |

**索引**：`IDX(company_id, create_time)`、`IDX(feature, create_time)`、`IDX(job_id, create_time)`、`IDX(cache_hit)`、`IDX(trace_id)`

---

## 3.6 治理

### 3.6.1 `audit_log` —— 审计日志

**作用**：记录敏感数据访问与关键操作：谁在什么时候、从哪个 IP、对什么对象做了什么。**合规（个保法）与安全事件的唯一追溯依据**。

**何时写/读**：查看候选人完整信息、导出简历、删除 PII、改角色、批量操作时写入；管理员审计页查询。

**关键设计点**：
- **只追加不修改**，保留期按合规要求（建议 ≥ 6 个月）。
- `detail` 存变更前后摘要（如角色从 recruiter 改为 admin），便于回溯。
- 与业务日志分开：业务日志给开发看，审计日志给合规看。

| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|:--:|---|
| `id` | BIGINT | PK | | 主键 |
| `company_id` | BIGINT | IDX | | 所属公司 |
| `user_id` | BIGINT | IDX | NULL | 操作人（系统触发的为空） |
| `action` | VARCHAR(50) | NOT NULL, IDX | | `candidate.view_full`/`candidate.delete_pii`/`resume.export`/`user.role_change`/`job.publish` |
| `target_type` | VARCHAR(30) | IDX | NULL | `candidate`/`application`/`user`/`job` |
| `target_id` | BIGINT | IDX | NULL | 目标对象 id |
| `detail` | JSON | | `{}` | 变更摘要 |
| `ip` | VARCHAR(45) | | NULL | 来源 IP（兼容 IPv6） |
| `user_agent` | VARCHAR(255) | | NULL | 客户端标识 |
| `create_time` | DATETIME | NOT NULL, IDX | now | 发生时间 |

**索引**：`IDX(company_id, create_time)`、`IDX(target_type, target_id)`、`IDX(user_id, create_time)`、`IDX(action)`

---

## 3.7 对象存储设计（MinIO）

> 简历是二进制大文件，**不进数据库、也不放应用本地磁盘**，统一存 MinIO。数据库只存对象键（§3.2.4 的 `bucket` / `object_key`）。

### 3.7.1 为什么选 MinIO

| 理由 | 说明 |
|---|---|
| 二进制不入库 | BLOB 进数据库会让备份变慢、查询变重、迁移困难 |
| S3 协议兼容 | 本地跑 MinIO、生产可无缝换阿里云 OSS / AWS S3，只改 endpoint 与密钥 |
| 预签名 URL | 桶不需要公开，前端也能限时下载大文件，**不经过后端转发** |
| 本地可跑 | Docker 一条命令起，开发不依赖云服务 |
| 可备份 | 支持版本控制、生命周期规则、桶复制 |

### 3.7.2 桶与对象键设计

**桶（Bucket）规划**：

| 桶名 | 用途 | 保留策略 |
|---|---|---|
| `talentmatch-resume` | 简历原始文件（主桶） | 长期，候选人删除时同步删对象 |
| `talentmatch-attachment` | 其他附件（JD 附件、导出报告） | 后续需要再加 |
| `talentmatch-backup` | 归档/备份（可选） | 按合规要求 |

**对象键（Object Key）规则**：

```
{company_id}/resume/{yyyy}/{mm}/{uuid}.{ext}

示例：
1/resume/2026/11/6f2c1a9e-4b7d-4c2a-9e8f-3d5b1a0c7e21.pdf
```

必须遵守：
1. **不含候选人姓名/手机/邮箱等 PII**——对象键可能出现在 URL、日志中，绝不能带个人信息。
2. **用 UUID** 保证唯一且不可枚举（防止猜到别人简历的 URL）。
3. **按年/月分目录**，避免单目录对象过多影响列表性能。
4. **保留扩展名**，便于推断 `Content-Type` 与前端预览。

### 3.7.3 存储抽象接口（Storage Provider）

不要到处直接调 MinIO SDK，统一封装一层，**MinIO 是默认实现，本地磁盘是降级实现**：

```
StorageProvider:
    put(key, data, content_type) -> {etag, size}      # 上传对象
    get(key) -> bytes                                  # 服务端读取（解析用）
    presign_get(key, expires=600) -> url               # 生成限时下载链接
    delete(key)                                        # 删除对象
    exists(key) -> bool                                # 存在性检查
    stat(key) -> {size, etag, last_modified}           # 元信息
```

**配置**：

```env
STORAGE_BACKEND=minio        # minio | local
MINIO_ENDPOINT=127.0.0.1:9000
MINIO_ACCESS_KEY=talentmatch
MINIO_SECRET_KEY=change-me
MINIO_BUCKET=talentmatch-resume
MINIO_SECURE=false
```

**降级设计**：`STORAGE_BACKEND=local` 时用本地目录实现同一接口。好处是——**MinIO 没起来也能开发/测试**，不至于卡住进度；切回 MinIO 只改一个环境变量。

### 3.7.4 上传流程

```
前端选择文件
   │
   ▼ ① 后端校验：类型白名单(pdf/docx/jpg/png)、大小(≤20MB)
   │
   ▼ ② 计算 sha256
   │    命中已有 resume_file（同文件重复上传）→ 直接复用，返回"已存在"
   │
   ▼ ③ 未命中 → 生成 object_key → storage.put() 上传到 MinIO
   │
   ▼ ④ 写 resume_file：bucket/object_key/etag/sha256/size/status=pending
   │
   ▼ ⑤ 入队解析任务 → status=parsing
```

**要点**：
- 先落对象、再写库：如果写库失败，对象成孤儿（由清理任务处理）；反过来（先写库后上传）会出现"库里有记录但文件不存在"，更难处理。
- 批量上传时每份独立处理，一份失败不影响其他。

### 3.7.5 下载 / 预览流程

```
前端请求 GET /resumes/files/{id}/url
   │
   ▼ ① 鉴权：角色校验 + 数据归属校验（别人的简历返回 404）
   │
   ▼ ② 写审计：audit_log(action='resume.download', target=candidate)
   │
   ▼ ③ 生成预签名 URL（默认 10 分钟过期）
   │
   ▼ ④ 返回 URL → 前端直接从 MinIO 拉取文件
        （大文件不经过后端转发，省带宽省内存）
```

**为什么用预签名 URL 而不走后端代理**：简历 PDF 动辄几 MB，后端转发会占用 worker 与带宽；预签名 URL 让浏览器直连对象存储，后端只负责鉴权。

### 3.7.6 一致性与清理（必须做）

| 异常场景 | 后果 | 处理 |
|---|---|---|
| 对象上传成功，但写库失败 | MinIO 里留下孤儿对象 | 定时任务扫描：对象创建 > 24h 且 DB 无对应记录 → 删除 |
| 写库成功，但对象丢失 | 打开文件报错 | `resume_file.status=failed`，提示重新上传 |
| 删除候选人 PII | 对象不该再留 | 先 `storage.delete(object_key)`，再逻辑删库记录 |
| 解析失败 | 文件还在 | 保留对象，允许重新解析（不必重传） |

### 3.7.7 权限与安全

1. **桶不公开**：MinIO 桶策略只允许服务端 AK/SK 访问，禁止匿名读。
2. **预签名 URL 短时效**：默认 10 分钟，签名不可伪造、不可猜测。
3. **MinIO 不暴露公网**：开发仅监听本机；生产由 Nginx 反代 + 后端鉴权，或只允许内网访问。
4. **访问留痕**：每次生成下载 URL 都必须写 `audit_log`，满足"个人信息访问审计"。
5. **密钥管理**：AK/SK 走环境变量/密钥管理，不入库、不写进代码。

### 3.7.8 部署（阶段一）

`docker-compose.yml` 增加 MinIO 服务：

```yaml
minio:
  image: minio/minio
  command: server /data --console-address ":9001"
  environment:
    MINIO_ROOT_USER: talentmatch
    MINIO_ROOT_PASSWORD: change-me
  ports:
    - "9000:9000"   # S3 API
    - "9001:9001"   # 控制台
  volumes:
    - ./data/minio:/data
```

初始化脚本（幂等建桶）：

```
客户端连 MinIO → bucket_exists? → 不存在则 make_bucket
同时设置桶策略为 private
```

> 部署检查：启动后访问 `http://localhost:9001` 能登录控制台，能看到 `talentmatch-resume` 桶。

---

# 四、枚举与状态机

## 4.1 枚举速查表

| 表.字段 | 取值 | 含义 |
|---|---|---|
| `user.role` | `recruiter` / `manager` / `admin` | 招聘专员 / 用人经理 / 管理员 |
| `user.status` | `active` / `disabled` | 正常 / 禁用 |
| `job.status` | `draft` / `pending` / `published` / `closed` / `archived` | 草稿 / 待审批 / 招聘中 / 已关闭 / 已归档 |
| `job.employment_type` | `fulltime` / `intern` / `parttime` | 全职 / 实习 / 兼职 |
| `job.education_level` | `college` / `bachelor` / `master` / `phd` | 大专 / 本科 / 硕士 / 博士 |
| `resume_file.status` | `pending` / `parsing` / `success` / `failed` | 待解析 / 解析中 / 成功 / 失败 |
| `resume_file.source` | `upload` / `careers_page` / `email` | HR 上传 / 候选人投递 / 邮件导入 |
| `application.status` | `new` / `screening` / `interview` / `offer` / `hired` / `rejected` | 见状态机 |
| `match_result.scope` | `application` / `talent_pool` | 只匹配应聘者 / 匹配全人才库 |
| `match_result.reason_source` | `llm` / `template` | 模型生成 / 模板降级 |
| `interview.status` | `scheduled` / `done` / `cancelled` / `no_show` | 已安排 / 已完成 / 已取消 / 爽约 |
| `interview.type` | `phone` / `video` / `onsite` | 电话 / 视频 / 现场 |
| `interview_feedback.conclusion` | `pass` / `reject` / `hold` | 通过 / 不通过 / 待定 |
| `notification.channel` | `inapp` / `email` / `sms` / `webhook` | 站内信 / 邮件 / 短信 / 回调 |
| `notification.status` | `pending` / `sent` / `failed` / `read` | 待发 / 已发 / 失败 / 已读 |
| `chat_message.role` | `user` / `assistant` / `system` | 用户 / 助手 / 系统 |
| `chat_message.card_type` | `upload` / `parse_result` / `match_rank` / `interview` / `confirm` / `chart` | 卡片类型 |
| `agent_trace.status` | `success` / `failed` / `timeout` / `skipped` / `degraded` | 成功 / 失败 / 超时 / 跳过 / 降级 |
| `ai_call.feature` | `resume_parse` / `jd_generate` / `match_explain` / `interview_generate` / `analytics_insight` | 调用场景 |

> 实现建议：枚举值统一在代码里定义常量类，数据库用 `VARCHAR` + 应用层校验（不用 MySQL ENUM，改枚举要改表结构）。

## 4.2 应聘状态机

```
                    ┌──────────┐
                    │   new    │  新申请
                    └────┬─────┘
                         ▼
                    ┌──────────┐
                    │screening │  筛选中
                    └────┬─────┘
                         ▼
                    ┌──────────┐
                    │interview │  面试中
                    └────┬─────┘
                         ▼
                    ┌──────────┐
                    │  offer   │  Offer
                    └────┬─────┘
                         ▼
                    ┌──────────┐
                    │  hired   │  已入职（终态）
                    └──────────┘

  任意非终态（new/screening/interview/offer）
        │  必须填写 rejected_reason
        ▼
   ┌──────────┐
   │ rejected │  已淘汰（终态）
   └──────────┘
```

**规则**：
1. 只能沿箭头方向前进，不能跳级（`new → offer` 非法）。
2. 任意非终态可转 `rejected`，但**必须填原因**。
3. `hired` / `rejected` 是终态，不允再流转（管理员"撤回"走特殊接口并写审计）。
4. 每次流转：更新 `status` + `stage_entered_at`，写一条 `application_stage_history`，触发通知。

**职位状态机**：
```
draft → pending（提审批）→ published（审批通过）→ closed（关闭）→ archived（归档）
                └→ draft（审批驳回，带 reject_reason）
published ─────→ closed / archived
```

---

# 五、索引与性能

## 5.1 索引设计清单（关键索引）

| 表 | 索引 | 支撑的查询 |
|---|---|---|
| `job` | `(company_id, status, update_time)` | 职位列表：按状态筛 + 按更新时间排序 |
| `job` | `(title)` | 职位名搜索 |
| `candidate` | `UQ(dedupe_key)` | 简历去重的唯一判断 |
| `candidate` | `(email_hash)` / `(phone_hash)` | 按邮箱/手机查人 |
| `resume_file` | `UQ(sha256)` | 重复上传命中 |
| `resume_file` | `(status)` | 扫描待解析任务 |
| `resume` | `(content_hash)` | 匹配缓存查找 |
| `application` | `UQ(job_id, candidate_id)` | 防重复投递 |
| `application` | `(job_id, status)` | 看板按职位分列 |
| `application` | `(stage_entered_at)` | SLA 超时扫描 |
| `match_result` | `(job_id, score)` | 排名页按分数排序 |
| `match_result` | `(fingerprint)` | 缓存命中判断 |
| `agent_trace` | `(trace_id, step_no)` | 轨迹面板按序展示 |
| `ai_call` | `(company_id, create_time)` | 月度成本汇总 |
| `ai_call` | `(feature, create_time)` | 按功能看成本 |
| `audit_log` | `(target_type, target_id)` | 查某对象的操作历史 |

## 5.2 慢查询预防

| 场景 | 风险 | 对策 |
|---|---|---|
| 职位列表带应聘数 | 每次 COUNT 子查询 | 用 `job.apply_count` 冗余字段 |
| 匹配排名 | 全表算分很慢 | 结果落 `match_result`，只算增量；分页读 |
| 人才库检索 | JSON 字段过滤慢 | 高频过滤字段（技能）落独立列或建关联表（后续优化） |
| 成本报表 | 明细表越来越大 | 按月汇总表 `ai_call_monthly`（后续加），明细保留 3 个月 |
| 轨迹查询 | trace 表增长快 | 按 `create_time` 分区/定期归档 |

---

# 六、数据生命周期与合规

## 6.1 保留策略

| 数据 | 保留期 | 处理方式 |
|---|---|---|
| 简历文件与解析结果 | 候选人主动删除前长期保留 | 逻辑删除 + 物理文件清理 |
| 应聘记录与状态历史 | 3 年（劳动法相关） | 到期归档 |
| AI 调用明细 | 12 个月 | 月度汇总后清理明细 |
| 编排轨迹 | 6 个月 | 到期归档 |
| 审计日志 | ≥ 6 个月（建议 3 年） | 只增不删 |
| 对话会话 | 12 个月 | 用户可自行删除 |

## 6.2 PII 处理规则

| 字段 | 存储 | 展示 | 访问控制 |
|---|---|---|---|
| 手机号、邮箱 | **Fernet 加密**（`_enc`）+ hash（去重） | 列表脱敏 `138****0001` | 查看完整值需二次确认 + 写审计 |
| 姓名 | 明文 | 明文 | 正常 |
| 身份证/住址 | **不采集** | — | 避免合规风险 |
| 性别/年龄/婚育 | **不采集** | — | 避免 AI 偏见（PRD §12） |
| 简历原文 | 明文存 **MinIO**（桶不公开） | 有权限才可下载 | 下载写审计 |

## 6.3 删除权（PIPL）

候选人要求删除时：
1. `candidate.is_deleted = 1`、`deleted_at = now`。
2. 清空 `phone_enc` / `email_enc` / `resume_text` / `skills`。
3. **删除 MinIO 对象**（`storage.delete(resume_file.object_key)`），再逻辑删除简历记录。
4. **保留** `application` 与 `audit_log`（统计与合规需要，但不再关联 PII）。
5. 写一条 `audit_log`（`action = candidate.delete_pii`）。

## 6.4 审计要求

必须写审计的动作：
- 查看候选人完整联系方式
- 下载/导出简历
- 删除候选人 PII
- 修改用户角色 / 禁用账号
- 发布/关闭职位
- 批量状态变更
- 修改 LLM 配置（含 API Key）

---

# 七、分阶段建表计划

| 阶段 | 建表 | 说明 |
|:--:|---|---|
| 一 | `company`、`user`、`llm_config`、`skill`、`job`、`candidate`、`resume_file`、`resume`、`application`、`application_stage_history`、`match_result`、`ai_call`、`audit_log`（13 张） | 一次建齐核心，避免后期频繁改表 |
| 二 | `auth_token`（1 张）；`user` 增加 `email_verified_at`、`token_version` | 邮箱验证、找回密码、登出吊销令牌 |
| 六 | `interview`、`interview_feedback`、`notification`（3 张） | 面试安排与通知 |
| 九 | `agent_trace`（1 张） | 编排轨迹 |
| 九½ | `chat_session`、`chat_message`（2 张） | 对话持久化 |

---

# 八、与 PRD 第 7 章对照

| PRD 表 | PRD 字段要求 | 本设计落地 | 差异与理由 |
|---|---|---|---|
| `jobs`（7.2.1） | id/company_id/title/description/requirements/skills/status/created_at | `job` | 补齐部门/地点/薪资/headcount/`must_have_skills`/`jd_version`；`skills` 存归一 id 而非自由文本 |
| `candidates`（7.2.2） | id/name/email/phone/resume_data/skills/created_at | `candidate` + `resume` + `resume_file` | **拆三表**：人 / 文件 / 解析结果分离，避免大 JSON 塞主表；PII 加密 |
| `applications`（7.2.3） | id/job_id/candidate_id/match_score/status/applied_at | `application` + `application_stage_history` | 增加来源渠道、`stage_entered_at`、流转历史（周期分析必需） |
| `ai_calls`（7.2.4） | id/user_id/job_id/model_name/input_tokens/output_tokens/cost/created_at | `ai_call` | 增加 `feature`/`agent`/`cache_hit`/`trace_id`，支持按功能统计与缓存收益分析 |
| `companies` | 被 `company_id` 引用 | `company` | 单公司部署仅 1 行，为多租户预留 |
| （PRD 未列） | — | `skill`、`user`、`llm_config`、`match_result`、`interview`、`interview_feedback`、`notification`、`chat_*`、`agent_trace`、`audit_log` | PRD 只给了 4 张核心表；实际系统必需的账号、技能归一、可解释匹配、面试、通知、会话、轨迹、审计 |

---

# 九、关键设计决策（ADR）

| # | 决策 | 理由 | 代价 / 备注 |
|:--:|---|---|---|
| 1 | 主键用自增 BIGINT，不用 UUID | 单库单公司，自增更快、索引更小、调试友好 | 若未来分库需改造；对外不暴露 |
| 2 | 逻辑外键，不建物理外键约束 | 便于迁移/分库；避免误级联删业务数据 | 完整性由服务层保证，需在测试里覆盖 |
| 3 | 简历拆 file / resume / candidate 三表 | 一人多份简历、一份多版本；大 JSON 不塞主表 | 查询需多表 JOIN，用冗余字段缓解 |
| 4 | PII 加密 + hash 索引 | 既满足隐私合规，又能去重查找 | 加密字段无法模糊搜索 |
| 5 | 匹配结果落库 + fingerprint 缓存 | 避免重复计算与重复计费；可解释性 | 需正确维护 `jd_version` 与 `content_hash` |
| 6 | 状态历史独立表、只追加 | 周期分析与审计依赖；不可篡改 | 表会持续增长，需归档策略 |
| 7 | 编排轨迹与 AI 计量分表 | 一个 step 可能 0~N 次模型调用，分表语义清晰 | 需 `trace_id` 关联 |
| 8 | 对话消息存结构化卡片而非 HTML | 前端可重渲染、可换 UI | 卡片 schema 需版本管理 |
| 9 | 时间统一存 UTC | 避免时区混乱 | 展示层统一转 Asia/Shanghai |
| 10 | 枚举用 VARCHAR + 应用层校验 | 改枚举不必改表结构 | 需在代码里集中定义常量 |
| 11 | **简历文件存 MinIO，DB 只存对象键** | 二进制不入库；S3 兼容可迁移；预签名 URL 免开放桶 | 需处理孤儿对象清理与 MinIO 可用性；用 `StorageProvider` 抽象可降级本地 |
| 12 | **对象键用 UUID、不含 PII** | 对象键会出现在 URL/日志中，不能带个人信息；UUID 不可枚举 | 无法按姓名直接找文件（业务上也不需要） |

---

# 十、附录：初始种子数据建议

| 表 | 初始数据 | 数量 |
|---|---|---|
| `company` | 演示公司 1 条（含品牌色与 careers_slug） | 1 |
| `user` | 三个角色账号（`recruiter` / `manager` / `admin`），邮箱已验证，密码统一 `Talent@2026`（`scripts/seed_users.py` 生成） | 3 |
| `skill` | 常见技能 + 别名（语言/框架/数据库/中间件/工具/软技能） | 200+ |
| `job` | 3 个职位（1 招聘中 / 1 草稿 / 1 已关闭） | 3 |
| `candidate` | 演示候选人（含技能与经历） | 10 |
| `resume` / `resume_file` | 与候选人对应的样例简历 | 10 |
| `application` | 覆盖各状态（new/screening/interview/offer/hired/rejected） | 20 |
| `match_result` | 对 1 个职位跑一次匹配 | 10 |
| `ai_call` | 演示计量数据（可选，或跑真实调用产生） | — |

> 种子数据的作用：让演示不必现场造数据，也让看板/漏斗/成本页在第一次启动时就有内容。

---

> **文档版本**：V1 · 对应设计《项目设计方案_V1》§7
> **维护方式**：改表结构时同步改本文；实现阶段建议用脚本从模型自动导出字段表校验一致性（防止文档与代码脱节）。
