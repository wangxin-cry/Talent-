# TalentMatch

**AI 驱动的企业智能招聘 Agent 平台**

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688)
![Vue](https://img.shields.io/badge/Vue-3.5-42B883)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791)
![LangGraph](https://img.shields.io/badge/LangGraph-1.0-1C3C3C)

面向企业 HR 团队的多租户招聘平台：公司入驻、职位管理、简历解析、人岗匹配、AI 面试辅助、招聘流程自动化、数据分析与 AI 成本监控。

核心特点：**一家公司一套数据** + **多 Agent 编排** + **RAG 知识增强** + **对话式操作入口**。

---

## 目录

- [项目简介](#项目简介)
- [功能特性](#功能特性)
- [技术栈](#技术栈)
- [系统架构](#系统架构)
- [快速开始](#快速开始)
- [默认账号](#默认账号)
- [配置说明](#配置说明)
- [目录结构](#目录结构)
- [接口概览](#接口概览)
- [角色与权限](#角色与权限)
- [测试](#测试)
- [部署](#部署)
- [已知限制](#已知限制)
- [声明](#声明)

---

## 项目简介

传统招聘工具大多停留在"存简历 + 打分"的层面，业务数据散落在 Excel、邮件和聊天记录里。TalentMatch 试图把一条完整的招聘链路放进同一个系统：

```
简历上传 → 结构化解解析 → 人岗匹配 → 流程推进 → 面试辅助 → 数据复盘
```

同时用 LLM 承担其中"需要理解语义"的部分（简历字段抽取、JD 生成、面试题、语义检索、对话式操作），而**所有涉及状态流转和权限的判断仍由确定性代码完成**，避免模型幻觉影响业务正确性。

系统包含三个使用端：

| 端 | 使用者 | 入口 |
|---|---|---|
| 招聘工作台 | HR / 用人经理 / 招聘专员 | 登录后的主应用 |
| 招聘官网 | 外部候选人（无需登录） | `/careers/{公司标识}` |
| 平台运营 | 平台超级管理员 | `/platform` |

---

## 功能特性

### 多租户与账号体系

- 公司自助注册：创建新公司，或凭邀请码加入已有公司
- 全表 `company_id` 隔离，跨公司访问统一返回 404（不暴露资源是否存在）
- 邮箱验证、找回密码、JWT 双令牌（访问 30 分钟 / 刷新 7 天）
- `token_version` 机制：登出、改密、禁用、注销后旧令牌立即失效
- 手机号、邮箱等 PII 字段 Fernet 加密落库，日志脱敏

### 简历解析

- 支持 PDF、DOCX、图片，单文件 ≤ 20 MB，单批 ≤ 10 个
- 文本 PDF 走 pdfplumber / pypdf，DOCX 走 python-docx，扫描件渲染后走 OCR
- LLM 结构化抽取 + **字段置信度**，低置信字段前端标黄提示人工校对
- 同公司内按 `sha256` 去重，同一候选人按"手机号 → 邮箱 → 文件哈希"三级合并

### 可解释人岗匹配

- 规则特征（必备/加分技能、年限、学历、地点）+ 向量相似度综合打分
- 每个结果附分项解释：命中项、缺失项、加分项
- 缓存指纹 = `sha256(算分版本 + JD 版本 + 简历内容哈希)`，内容未变不重复调用模型
- 支持人工反馈（有用 / 无用），用于后续调参

### RAG 与人才库

- 简历切片入库，FAISS 向量检索（未安装 FAISS 时自动降级为 numpy）
- 向量与业务主键绑定，更新先删后写、删除同步清理
- 检索按公司隔离，只返回本公司数据
- 提供索引重建入口

### 多 Agent 编排

基于 LangGraph 的 Supervisor 模式：

```
Supervisor
 ├── 简历解析 Agent
 ├── 匹配 Agent
 ├── 面试题 Agent
 ├── JD 写作 Agent
 ├── 流程流转 Agent
 └── 数据分析 Agent
```

- 按意图与槽位路由，上下文总线复用上游产出
- 每步记录 `AgentTrace`（成功 / 失败 / 超时 / 降级），可回放
- LLM 不可用时自动降级到模板逻辑，链路不中断

### 对话式入口

- 自然语言发起操作：上传简历、批量匹配、生成面试题、查看看板
- 安全闸分级：`read` 直接执行，`write` 先出计划待确认，`irreversible` 强制二次确认
- 返回结构化卡片（上传、解析结果、匹配排名、面试、图表、确认）

### 招聘流程与面试

- 状态机：`新投递 → 筛选中 → 面试中 → Offer → 已入职`，任意阶段可淘汰
- 拖拽式看板，记录每阶段停留时长，超 SLA 标红
- 面试题必须引用候选人具体项目 / 技能 / 岗位缺口，禁止通用题
- 面试安排支持导出 `.ics`，面试记录含六维评估
- 候选人每次状态变更自动发邮件（附进度查询链接）

### 数据看板与成本

- 在招职位、投递量、待面试、平均招聘周期
- 漏斗转化、渠道效果、各阶段平均停留
- 每次真实 LLM 调用写入 `ai_call` 台账（模型、token、耗时、成本）
- 按公司汇总成本，支持月度预算告警与 Excel 报表导出

### 安全性

- 全局限流：每用户 / API Key / IP 100 次/分钟，超限返回 429 + `Retry-After`
- 登录失败 5 次锁定 15 分钟
- bcrypt 密码哈希；JWT 签名校验；API Key 只存哈希
- 异常统一结构，生产环境不暴露堆栈
- 审计日志记录关键操作（用户变更、配置修改、职位发布等）

---

## 技术栈

### 后端

| 技术 | 版本 | 用途 |
|---|---|---|
| Python | 3.11+ | 运行环境 |
| FastAPI | ≥ 0.115 | HTTP 接口、依赖注入、自动文档 |
| Uvicorn | ≥ 0.30 | ASGI 服务器，可选托管前端静态资源 |
| Pydantic v2 / pydantic-settings | ≥ 2.7 | 参数校验与配置加载 |
| SQLAlchemy（async） | ≥ 2.0 | 异步 ORM |
| asyncpg / aiosqlite | — | PostgreSQL / SQLite 异步驱动 |
| Alembic | ≥ 1.13 | 迁移工具（当前以 `create_all` + 启动兼容迁移为主） |
| Celery + Redis | ≥ 5.4 | 简历解析、RAG 索引异步化（可选） |
| LangGraph | ≥ 1.0 | 多 Agent 编排 |
| FAISS / numpy | ≥ 1.8 / ≥ 1.26 | 向量检索与降级实现 |
| pdfplumber / pypdf / PyMuPDF / python-docx / Pillow | — | 多格式简历解析 |
| httpx | ≥ 0.27 | 调用 OpenAI 兼容的 LLM / Embedding / OCR 接口 |
| passlib + bcrypt / python-jose / cryptography | — | 密码哈希、JWT、PII 加密 |
| MinIO SDK | ≥ 7.2 | 简历文件对象存储 |
| loguru | ≥ 0.7 | 结构化日志与脱敏 |
| pytest + pytest-asyncio | ≥ 8 | 后端测试 |

### 前端

| 技术 | 版本 | 用途 |
|---|---|---|
| Vue 3 | 3.5 | 页面与组件（Composition API） |
| TypeScript | 5.6 | 类型约束 |
| Vite | 5.4 | 开发与构建 |
| Element Plus | 2.8 | UI 组件库 |
| Pinia | 2.2 | 登录态与用户信息 |
| Vue Router | 4.4 | 路由与登录守卫 |
| axios | 1.7 | 请求封装、令牌注入、401 统一处理 |

### 基础设施

| 组件 | 用途 | 是否必需 |
|---|---|---|
| SQLite | 开发态数据库 | 二选一 |
| PostgreSQL 16 | 生产数据库 | 二选一 |
| 本地磁盘 | 开发态文件存储 | 二选一 |
| MinIO | 生产文件存储（私有桶 + 预签名下载） | 二选一 |
| Redis | Celery broker | 可选 |
| LLM 服务（OpenAI 兼容协议） | 抽取、JD、面试题、对话、Embedding | 可选（可 Mock） |

---

## 系统架构

```
┌───────────────────────────── 浏览器 ─────────────────────────────┐
│  Vue 3 + Element Plus（招聘端 / 候选人端 / 平台运营端）           │
└──────────────────────────────┬───────────────────────────────────┘
                               │ HTTP（JWT 或 X-API-Key）
┌──────────────────────────────▼───────────────────────────────────┐
│                         FastAPI（ASGI）                          │
│  中间件：CORS / 全局限流 / X-Process-Time                         │
│  鉴权：get_current_user → 绑定公司上下文 → 角色与数据范围          │
│  路由：auth company platform admin jobs candidates matching …     │
│  服务层：业务规则、状态机、审计、通知、成本台账                     │
└───┬──────────────┬───────────────┬──────────────┬────────────────┘
    │              │               │              │
┌───▼─────┐  ┌─────▼──────┐  ┌─────▼──────┐  ┌────▼─────────────┐
│PostgreSQL│  │   MinIO    │  │Redis+Celery│  │ LLM / Embedding  │
│ 业务数据 │  │  简历文件  │  │ 解析 / 索引│  │      / OCR       │
└──────────┘  └────────────┘  └────────────┘  └──────────────────┘
                                     │
                            ┌────────▼────────┐
                            │  FAISS 向量索引 │
                            └─────────────────┘
```

请求处理顺序：认证 → 绑定公司上下文（`ContextVar`）→ 计算数据范围 → 服务层执行 → 写审计 / 通知 / 成本记录。

核心链路：

```
简历：上传 → MinIO/本地 → 队列 → 解析 → LLM 抽取 → 人工校对 → 建候选人档案 → 写向量
匹配：选职位 → 规则特征 + 向量相似度 → 指纹缓存 → 排名 + 逐项解释 → 人工反馈
对话：输入 → 意图识别 → 槽位抽取 → 安全闸 → Supervisor 调度子 Agent → 结构化卡片
```

---

## 快速开始

### 环境要求

- Python **3.11+**
- Node.js **18+**（含 npm）
- 可选：Docker（用于 PostgreSQL / MinIO）

### 方式一：本地极简运行（SQLite + 本地存储 + Mock LLM）

无需安装数据库和对象存储，适合先跑起来看效果。

```bash
git clone <你的 Gitee 仓库地址> TalentMatch
cd TalentMatch
```

**1）创建虚拟环境并安装依赖**

```bash
python -m venv .venv

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

pip install -r backend/requirements.txt
```

**2）准备配置**

```bash
# Windows
Copy-Item .env.example .env
# macOS / Linux
cp .env.example .env
```

默认配置即可运行：`DATABASE_URL` 留空使用 SQLite，`STORAGE_BACKEND=local`，`LLM_MOCK=true`。

**3）初始化数据**（在项目根目录执行）

```bash
python scripts/init_db.py       # 建表
python scripts/seed_skills.py   # 技能词表
python scripts/seed_users.py    # 可选：演示账号
```

**4）启动后端**

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

**5）启动前端**（另开终端）

```bash
cd frontend
npm install
npm run dev
```

### 方式二：使用 Docker 启动 PostgreSQL + MinIO

```bash
docker compose up -d
```

启动后修改 `.env`：

```env
DATABASE_URL=postgresql+asyncpg://talentmatch:talentmatch@127.0.0.1:5432/talentmatch
STORAGE_BACKEND=minio
MINIO_ENDPOINT=127.0.0.1:9000
MINIO_ACCESS_KEY=talentmatch
MINIO_SECRET_KEY=talentmatch123
```

再执行初始化：

```bash
python scripts/init_db.py
python scripts/init_minio.py
python scripts/seed_skills.py
```

> PostgreSQL 数据卷落在 `./data/postgres`，MinIO 数据卷落在 `./data/minio`，均已被 `.gitignore` 忽略。

### 方式三：单端口运行（后端托管前端构建产物）

```bash
cd frontend
npm run build
cd ..

# 设置环境变量后启动
set SERVE_FRONTEND=true        # Windows PowerShell: $env:SERVE_FRONTEND="true"
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Windows 下也可直接使用脚本：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -Build
```

### 访问地址

| 地址 | 说明 |
|---|---|
| <http://127.0.0.1:5173> | 前端开发服务器 |
| <http://127.0.0.1:8000> | 后端接口 / 单端口部署入口 |
| <http://127.0.0.1:8000/docs> | Swagger 接口文档 |
| <http://127.0.0.1:8000/api/v1/healthz> | 健康检查（数据库 / 对象存储 / 队列） |

---

## 默认账号

演示账号由 `scripts/seed_users.py` 创建，密码统一为 `Talent@2026`，仅用于本地演示：

| 账号 | 邮箱 | 角色 |
|---|---|---|
| `recruiter` | `recruiter@talentmatch.local` | 招聘专员 |
| `manager` | `manager@talentmatch.local` | 用人经理 |
| `admin` | `admin@talentmatch.local` | 公司管理员 |

平台超级管理员不隶属任何公司，需单独创建：

```bash
cd backend
python scripts/create_superadmin.py --email boss@example.com --name boss --password "Passw0rd!"
```

---

## 配置说明

所有配置通过 `.env` 读取，模板见 [.env.example](.env.example)。常用项：

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `APP_ENV` | `dev` | `dev` / `test` / `prod` |
| `DEBUG` | `true` | 是否输出调试信息 |
| `SERVE_FRONTEND` | `false` | 为 `true` 时后端托管 `frontend/dist` |
| `SECRET_KEY` | `change-me-in-production` | **生产必须替换** |
| `DATABASE_URL` | 空（SQLite） | 留空用 `data/talentmatch.db`；PG 示例见上方 |
| `STORAGE_BACKEND` | `local` | `local` / `minio` |
| `MAX_UPLOAD_MB` | `20` | 单文件上传上限 |
| `QUEUE_MODE` | `memory` | `memory`（进程内） / `celery`（Redis 队列） |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | Celery broker |
| `RATE_LIMIT_ENABLED` | `true` | 是否启用全局限流 |
| `RATE_LIMIT_PER_MINUTE` | `100` | 每用户 / IP 每分钟请求数 |
| `LLM_BASE_URL` | OpenAI 兼容地址 | 任意兼容服务均可接入 |
| `LLM_API_KEY` | 空 | 为空且 `LLM_MOCK=true` 时走 Mock |
| `LLM_MOCK` | `true` | 无 Key 时保持 `true`，AI 链路仍可跑通 |
| `RAG_ENABLED` | `true` | 是否启用 RAG |
| `VECTOR_BACKEND` | `faiss` | `faiss` / `numpy` / `auto` |
| `EMBEDDING_DIM` | `1024` | 需与所选 Embedding 模型一致 |
| `EMAIL_HOST` | 空 | 为空时验证链接只打印到后端日志（搜 `[DEV]`） |
| `MONTHLY_BUDGET_CNY` | `500` | 月度 AI 预算告警阈值 |

> `.env` 已被 `.gitignore` 忽略，请勿提交真实密钥。生产环境至少需要修改 `SECRET_KEY`、关闭 `DEBUG`、收紧 `CORS_ORIGINS`。

---

## 目录结构

```
TalentMatch/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口：lifespan、CORS、限流、异常、静态托管
│   │   ├── core/                # 配置、数据库、存储、安全、依赖、限流、租户上下文
│   │   ├── models/              # ORM 模型（24 张表）
│   │   ├── schemas/             # Pydantic 出入参
│   │   ├── api/v1/              # 路由（18 个模块）
│   │   ├── services/            # 业务服务（认证、职位、简历、匹配、RAG、审计…）
│   │   ├── agents/              # Supervisor + 子 Agent、上下文总线
│   │   ├── chat/                # 对话引擎（意图、槽位、安全闸、卡片）
│   │   ├── ai/                  # LLM 客户端、抽取、缓存
│   │   └── workers/             # Celery 应用与任务
│   ├── scripts/                 # create_superadmin / reindex_rag
│   ├── tests/                   # 后端测试
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── api/                 # 接口封装
│       ├── stores/              # Pinia
│       ├── router/              # 路由与登录守卫
│       ├── views/               # 页面
│       ├── components/          # 公共组件
│       └── styles/              # 全局样式
├── scripts/                     # init_db / init_minio / seed_* / dev / start / worker
├── docker-compose.yml           # PostgreSQL + MinIO
├── .env.example                 # 配置模板
├── 部署.md                      # 环境准备、启动、排障
├── 全部改动.md                  # 开发过程与改动记录
└── data/                        # 运行期数据（已 gitignore）
```

---

## 接口概览

| 前缀 | 模块 |
|---|---|
| `/api/v1/auth` | 注册 / 登录 / 刷新 / 登出、邮箱验证、找回密码、个人资料、账号注销 |
| `/api/v1/company` | 邀请码查询、当前公司、成员管理 |
| `/api/v1/platform` | 平台超管：公司列表 / 新建 / 启停 |
| `/api/v1/admin` | 用户管理、系统配置、审计日志、API Key |
| `/api/v1/jobs` `/api/v1/skills` | 职位管理、技能词表、AI 生成 JD |
| `/api/v1/candidates` | 上传、解析状态、重解析、候选人增改查、下载 |
| `/api/v1/matching` | 批量匹配、排名、解释、反馈 |
| `/api/v1/applications` | 应聘记录、状态流转、看板、时间线 |
| `/api/v1/interviews` | 面试安排、ICS、评估、面试记录 |
| `/api/v1/public` | 公开招聘职位、在线投递、进度查询 |
| `/api/v1/notifications` | 站内通知 |
| `/api/v1/analytics` | 概览、漏斗、渠道、周期、SLA、报表导出 |
| `/api/v1/rag` | 语义检索、重建索引 |
| `/api/v1/orchestration` `/api/v1/chat` | 多 Agent 编排、对话 |
| `/api/v1/api-keys` | 个人 API Key |
| `/api/v1/healthz` | 健康检查 |

完整参数与示例见运行后的 `/docs`。

---

## 角色与权限

| 能力 | superadmin | admin | manager | recruiter |
|---|---|---|---|---|
| 平台公司管理 | 是 | 否 | 否 | 否 |
| 业务数据访问 | 否 | 全公司 | 部门 / 本人 | 本人 + 已发布职位只读 |
| 公司成员与邀请码 | 否 | 是 | 否 | 否 |
| 系统配置 / 审计 / API Key | 否 | 是 | 否 | 否 |
| 职位审批 | 否 | 是 | 是 | 否 |
| 职位创建 | 否 | 是 | 是 | 是 |
| 上传候选人 / 匹配 / 面试 | 否 | 是 | 是 | 是 |
| 自助注销账号 | 否 | 否 | 是 | 是 |

---

## 测试

```bash
cd backend
python -m pytest -q
```

当前覆盖：认证与权限、多租户隔离、职位状态机、简历解析、匹配打分、流程流转、RAG、Agent 编排、限流与异常结构等，共 128 项。

前端构建检查：

```bash
cd frontend
npm run build
```

---

## 部署

### 数据服务（Docker）

```bash
docker compose up -d          # PostgreSQL 5432 + MinIO 9000/9001
docker compose ps
```

### 启用 Celery 队列（可选）

适合简历批量解析等耗时操作。需要 Redis：

```env
QUEUE_MODE=celery
REDIS_URL=redis://127.0.0.1:6379/0
```

启动 worker：

```bash
cd backend
celery -A app.workers.celery_app:celery_app worker --loglevel=info
```

> Windows 下 Celery 建议加 `--pool=solo`。

### 生产要点

- 修改 `SECRET_KEY`，关闭 `DEBUG`，配置明确的 `CORS_ORIGINS`
- 前端执行 `npm run build`，后端设置 `SERVE_FRONTEND=true` 单端口托管；或用 Nginx 托管并回退 `index.html`
- 对象存储切换为 MinIO 私有桶，下载走预签名 URL
- 数据库定期备份；表结构变更前先备份
- 如需真实邮件，配置 `EMAIL_HOST` / `EMAIL_PORT` / `EMAIL_USE_SSL`，密码填邮箱授权码

更详细的启动顺序、PyCharm 配置与排障见 [部署.md](部署.md)。

---

## 已知限制

- 未配置 LLM Key 时使用 Mock 输出，语义能力有限；配置真实服务后效果取决于所选模型
- 表结构以 `create_all` + 启动兼容迁移为主，尚未接入完整的 Alembic 迁移流水线
- Windows 下 Celery 需使用 `--pool=solo`，并发能力有限
- 暂未实现：渠道成本归因、职位模板库、候选人满意度调研、多语言、移动端
- 向量检索默认单机 FAISS，未做分布式索引
