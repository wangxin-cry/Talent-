# TalentMatch —— AI 驱动的企业智能招聘 Agent 平台

> 面向企业 HR 团队的智能招聘平台：职位管理、简历解析、人岗匹配、AI 面试辅助、招聘流程自动化、数据分析与成本监控。
> 核心亮点：**多 Agent 编排（Manager + 子 Agent）+ RAG 知识增强 + 对话式操作入口**。

当前状态：**阶段一 · 工程骨架**（MinIO + PostgreSQL、健康检查、前后端可启动）

---

## 一、快速开始

### 前置

| 组件 | 要求 | 说明 |
|---|---|---|
| Python | 3.11 | 建议 conda 环境 |
| Node.js | 20+ | 前端 |
| Docker Desktop | 可选 | 需要 PostgreSQL + MinIO 时使用 |

### 方式 A：最省事（SQLite + 本地存储，无需 Docker）

```powershell
# 1. 后端依赖
cd backend
pip install -r requirements.txt

# 2. 配置
cd ..
Copy-Item .env.example .env      # 默认即为 SQLite + local 存储

# 3. 建表
python scripts/init_db.py

# 4. 起后端
cd backend
uvicorn app.main:app --reload --port 8000

# 5. 起前端（另开一个终端）
cd frontend
npm.cmd install
npm.cmd run dev
```

访问：
- 后端文档 <http://localhost:8000/docs>
- 健康检查 <http://localhost:8000/api/v1/healthz>
- 前端 <http://localhost:5173>

### 方式 B：PostgreSQL + MinIO（正式组合）

```powershell
# 1. 起数据库与对象存储（会自动建桶）
docker compose up -d

# 2. 改 .env：切到 PG + MinIO
#   DATABASE_URL=postgresql+asyncpg://talentmatch:talentmatch@127.0.0.1:5432/talentmatch
#   STORAGE_BACKEND=minio

# 3. 初始化
python scripts/init_db.py
python scripts/init_minio.py

# 4. 启动后端与前端（同方式 A）
```

MinIO 控制台 <http://localhost:9001>（账号见 `.env`）。

### 一键启动

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

---

## 二、项目结构

```
TalentMatch/
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI 入口（lifespan 建表、CORS、异常处理）
│   │   ├── core/                 # 基础设施
│   │   │   ├── config.py         #   配置（.env）
│   │   │   ├── database.py       #   SQLAlchemy 异步引擎与建表
│   │   │   ├── storage.py        #   对象存储抽象（MinIO + 本地降级）
│   │   │   ├── security.py       #   密码/JWT/PII 加解密
│   │   │   ├── deps.py           #   会话与 RBAC 依赖
│   │   │   └── logging.py        #   日志与 PII 脱敏
│   │   ├── models/               # 数据模型（13 张核心表）
│   │   ├── schemas/              # Pydantic 请求/响应模型
│   │   ├── api/v1/               # 路由（health / 后续业务路由）
│   │   ├── services/             # 业务服务层
│   │   ├── agents/               # 多 Agent（Manager + 子 Agent）
│   │   ├── ai/                   # LLM 客户端、抽取、缓存
│   │   └── workers/              # 后台任务
│   ├── tests/                    # pytest
│   └── requirements.txt
├── frontend/                     # Vue3 + TS + Element Plus + Vite
├── docs/                         # 设计文档（务必同步维护）
├── scripts/                      # init_db / init_minio / dev
├── data/                         # 运行期数据（已 gitignore）
├── docker-compose.yml            # PostgreSQL + MinIO
└── .env.example
```

---

## 三、设计文档

| 文档 | 内容 |
|---|---|
| [项目设计方案](docs/TalentMatch_项目设计方案_V1.md) | 产品定位、技术选型、架构、多 Agent 编排、十阶段计划 |
| [数据库设计](docs/TalentMatch_数据库设计_V1.md) | 19 张表逐字段说明、枚举状态机、索引、合规、MinIO 对象存储 |
| [对话式交互与产品画面](docs/TalentMatch_对话式交互与产品画面_V1.md) | 对话入口设计、Manager 如何调工具、界面与卡片 |
| [界面原型](docs/TalentMatch_界面原型.html) | 可直接打开的 HTML 原型 |

---

## 四、阶段进度

- [x] 阶段一：工程骨架（目录、配置、数据库、MinIO 抽象、健康检查）
- [ ] 阶段一：13 张核心表模型
- [ ] 阶段二：注册登录与三角色权限
- [ ] 阶段三：职位管理 + AI 生成 JD
- [ ] 阶段四：简历上传（MinIO）与多格式解析
- [ ] 阶段五：可解释人岗匹配
- [ ] 阶段六：候选人流程 + 面试辅助
- [ ] 阶段七：数据看板 + 成本监控
- [ ] 阶段八：RAG 知识增强
- [ ] 阶段九：多 Agent 编排
- [ ] 阶段九½：对话式入口
- [ ] 阶段十：部署交付

---

## 五、常用命令

```powershell
# 建表
python scripts/init_db.py

# 初始化 MinIO 桶
python scripts/init_minio.py

# 跑测试
cd backend; pytest -q

# 前端构建
cd frontend; npm.cmd run build
```

---

## 六、说明

- 简历等文件存 **MinIO**，数据库只存 `bucket` + `object_key`；下载走 10 分钟预签名 URL。
- 没有 LLM Key 时保持 `LLM_MOCK=true`，AI 链路仍可跑通。
- 开发默认 SQLite + 本地存储，随时可切 PostgreSQL + MinIO，只改 `.env`。
