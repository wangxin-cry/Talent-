# -*- coding: utf-8 -*-
"""生成 TalentMatch 任务看板 xlsx（6 个页签）。"""
import os
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "TalentMatch_任务看板.xlsx")

HEAD_FILL = PatternFill("solid", fgColor="1F3864")
HEAD_FONT = Font(color="FFFFFF", bold=True, size=11)
TITLE_FONT = Font(bold=True, size=14, color="1F3864")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)

SPRINT_FILL = {
    "Sprint 0": "FFF2CC",
    "Sprint 1": "DDEBF7",
    "Sprint 2": "E2EFDA",
    "Sprint 3": "FCE4D6",
    "Sprint 4": "E4DFEC",
    "Sprint 5": "D9E1F2",
    "Sprint 6": "EDEDED",
}

STEPS = [
    ["Step 0", "需求冻结与技术预研", "Sprint 0", 3, "—", "需求基线、标注集 v1、6 个 spike 结论、环境清单", "42 项需求表齐全；6 个 spike 有数字；标注集≥30 条", "—", "全部"],
    ["Step 1", "工程骨架 + 数据模型", "Sprint 1", 4, "S0", "13 张表、Alembic 首版、/healthz、前端脚手架、启动脚本", "/healthz 三组件 ok；迁移成功；前端能开", "—", "§7/§9"],
    ["Step 2", "用户中心与鉴权", "Sprint 1", 5, "S1", "9 个鉴权接口、三角色 RBAC、3 页面、审计", "6 鉴权用例全绿；锁定生效；越权 403", "M1.1", "UC-01~06"],
    ["Step 3", "职位管理", "Sprint 2", 4, "S2", "职位 CRUD、状态机、AI 生成 JD、技能词典 v1", "A1 全流程可用；AI 生成成功率≥90%", "M1.2", "JM-01~04"],
    ["Step 4", "简历上传与智能解析", "Sprint 2", 6, "S3", "四格式解析链、异步批量、去重、校对、解析页", "四字段准确率≥90%；100 份不阻塞", "M1.3", "RP-01~05"],
    ["Step 5", "智能人岗匹配", "Sprint 3", 6, "S4", "规则评分、可解释明细、排名、评测报告", "A3 一致率≥80%；100 份≤5s；缓存生效", "M1.4", "SM-01~04"],
    ["Step 6", "候选人库与应聘流程", "Sprint 3", 3, "S5", "候选人档案、状态机、流程看板", "6 条合法链通；5 条非法跳转 400", "—", "RA-03"],
    ["Step 7", "AI 面试辅助", "Sprint 3", 3, "S5", "问题生成、评估模板、面试记录", "A4 可用；≥70% 问题引用具体经历", "M1.5", "IA-01~03"],
    ["Step 8", "流程自动化与候选人体验", "Sprint 4", 5, "S6,S7", "通知中心、ICS 邀请、SLA 告警、投递页、进度查询", "A5 四类通知正确；投递页免登录可用", "M1.6", "RA-01/02/04,CE-01~03"],
    ["Step 9", "招聘数据分析", "Sprint 4", 5, "S6,S8", "6 个分析接口、看板、Excel 导出、口径文档", "A6 数据与手算一致；导出可打开", "M1.7", "DA-01~05"],
    ["Step 10", "AI 成本控制", "Sprint 4", 4, "S4,S5,S7", "统一 LLM 客户端、计量、缓存、预算、成本页", "每次调用可查；缓存命中>30%；超预算拦截", "—", "CC-01~03"],
    ["Step 11", "前端整体打磨", "Sprint 5", 5, "S3~S10", "信息架构、设计系统、通用组件、性能优化", "G1 首屏≤3s；G3 三浏览器可用", "—", "§8.1,G1/G3"],
    ["Step 12", "安全与合规加固", "Sprint 5", 4, "S2~S10", "限流、AES 加密、脱敏、审计、删除权、OWASP 自查", "G4 有证据；18 条越权断言全绿", "—", "§10,G4"],
    ["Step 13", "测试与质量收口", "Sprint 5", 4, "全部", "pytest 套件、覆盖率报告、冒烟脚本、评测回归", "覆盖率≥80%；冒烟一条命令跑通", "—", "§8.5"],
    ["Step 14", "部署与交付", "Sprint 6", 4, "全部", "compose、启动脚本、API/用户/部署文档、种子数据", "G5 文档齐全；15 分钟可跑起来", "—", "§9.3,G5"],
    ["Step 15", "验收与演示", "Sprint 6", 3, "全部", "验收报告、KPI 数字表、演示脚本、Q&A", "A1~A6 + G1~G5 全有证据；演示≤8 分钟", "—", "§14"],
]

TASKS = [
    # Step 0
    ["T0.1", "Step 0", "抽 42 项需求基线（优先级/Phase/验收方式/步骤）", "docs/需求基线.md", "42 行齐全且能逐条对 PRD", "—", 0.5, "P0", "全部"],
    ["T0.2", "Step 0", "写 ADR-001：技术栈、5 处偏离、不做什么", "docs/ADR-001-技术栈与边界.md", "能一句话说清 Phase1 边界", "T0.1", 0.5, "P0", "§3.2"],
    ["T0.3", "Step 0", "环境固化：py311 / npm.cmd / PG18 启动方式", "docs/环境清单.md", "每条命令 + 版本号可复现", "—", 0.5, "P0", "§9.1"],
    ["T0.4", "Step 0", "Spike A：6 份中文简历解析链路对比", "docs/spike-A-解析.md", "三种解析器各给出字段完整度数字", "T0.3", 0.5, "P0", "RP-01"],
    ["T0.5", "Step 0", "Spike B：LLM 结构化抽取 20 次稳定性", "docs/spike-B-抽取.md", "JSON 合法率/字段完整率有数据", "T0.3", 0.5, "P0", "RP-02"],
    ["T0.6", "Step 0", "Spike C：30 份简历人工标注 + 口径", "docs/标注集-v1.csv、标注口径.md", "≥30 条且口径可复述", "—", 0.5, "P0", "A3"],
    ["T0.7", "Step 0", "Spike D：队列方案（BackgroundTasks vs Celery）", "docs/spike-D-队列.md", "明确 QUEUE_MODE 设计", "T0.3", 0.2, "P0", "RP-05"],
    ["T0.8", "Step 0", "Spike E：单份解析+匹配成本估算", "docs/spike-E-成本.md", "1000 份月成本有数字", "T0.5", 0.3, "P1", "CC-01"],
    # Step 1
    ["T1.1", "Step 1", "建目录骨架（backend/frontend/docs/samples/scripts）", "目录树", "与路线图第 8 章一致", "T0", 0.3, "P0", "§9"],
    ["T1.2", "Step 1", "requirements.txt 一次性锁版本并装成", "backend/requirements.txt", "pip install 无冲突且导入通过", "T1.1", 0.7, "P0", "§9.1"],
    ["T1.3", "Step 1", "config.py 全量走 .env + .env.example", "app/core/config.py", "换机器只改 .env 可启动", "T1.2", 0.3, "P0", "§8.3"],
    ["T1.4", "Step 1", "database.py：async engine + SQLite WAL/PG 参数", "app/core/database.py", "两方言都能连", "T1.3", 0.3, "P0", "§9.2"],
    ["T1.5", "Step 1", "13 张表 + 索引 + 扩展字段", "app/models/models.py", "表齐全、字段注释、PRD 字段全覆盖", "T1.4", 1.0, "P0", "§7"],
    ["T1.6", "Step 1", "Alembic init + 首版迁移", "alembic/versions/0001", "upgrade head 成功", "T1.5", 0.4, "P1", "§7"],
    ["T1.7", "Step 1", "main.py：lifespan/CORS/统一异常/healthz", "app/main.py", "/healthz 返回三组件状态", "T1.5", 0.4, "P0", "§9.3"],
    ["T1.8", "Step 1", "deps.py：get_db/get_current_user/require_role 留桩", "app/core/deps.py", "依赖可注入，S2 直接填实现", "T1.7", 0.2, "P0", "§4.2"],
    ["T1.9", "Step 1", "前端脚手架（Next14+TS+Tailwind+shadcn）", "frontend/", "npm.cmd run dev 能开首页", "T1.1", 0.4, "P0", "§9.1"],
    ["T1.10", "Step 1", "dev.ps1 / migrate.ps1 两条脚本", "scripts/*.ps1", "一条命令起前后端", "T1.9", 0.2, "P1", "§9.3"],
    # Step 2
    ["T2.1", "Step 2", "schemas/user.py：注册/登录/Token/用户响应/角色", "app/schemas/user.py", "弱密码 422；api_key 掩码正确", "T1", 0.5, "P0", "UC-01/05"],
    ["T2.2", "Step 2", "security.py：bcrypt/JWT/jti 黑名单/Fernet 封装", "app/core/security.py", "登出后旧 token 失效", "T1", 0.8, "P0", "§8.3"],
    ["T2.3", "Step 2", "auth.py 九个接口（注册~api-key）", "app/api/v1/auth.py", "9 个接口可用且写审计", "T2.1,T2.2", 1.0, "P0", "UC-01~05"],
    ["T2.4", "Step 2", "登录失败 5 次锁定 15 分钟", "auth.py + login_attempts", "第 5 次 429；锁定期正确密码也拒", "T2.3", 0.4, "P0", "§6.1.3"],
    ["T2.5", "Step 2", "RBAC：权限矩阵 + require_role + 菜单隐藏", "core/permissions.py", "非 Admin 调 /admin/users 403", "T2.3", 0.5, "P0", "§4.2"],
    ["T2.6", "Step 2", "用户管理接口（列表/禁用/删除/改角色）", "api/v1/users.py", "4 个动作可用且写审计", "T2.5", 0.4, "P0", "UC-06"],
    ["T2.7", "Step 2", "审计日志（6 类动作）", "models + services/audit", "6 类动作各留一条", "T2.3", 0.3, "P1", "§10.2"],
    ["T2.8", "Step 2", "前端登录/注册/重置三页 + 路由守卫", "frontend/app/(auth)/*", "未登录访问跳登录；角色菜单正确", "T2.3", 0.8, "P0", "UC-04"],
    ["T2.9", "Step 2", "tests/test_auth.py 六用例", "backend/tests/test_auth.py", "6 个全绿", "T2.1~T2.8", 0.3, "P1", "§8.5"],
    # Step 3
    ["T3.1", "Step 3", "schemas/job.py + 状态枚举", "app/schemas/job.py", "字段覆盖 PRD 7.2.1 并含扩展", "T2", 0.4, "P0", "JM-01"],
    ["T3.2", "Step 3", "jobs.py：CRUD + 提交/审批/发布/关闭/归档", "app/api/v1/jobs.py", "6 个动作可用", "T3.1", 0.8, "P0", "JM-01~04"],
    ["T3.3", "Step 3", "职位状态机 + 发布前置校验", "services/job_state.py", "非法跳转 400；缺 requirements 422", "T3.2", 0.4, "P0", "JM-03"],
    ["T3.4", "Step 3", "AI 生成 JD（三段严格 JSON + 可编辑）", "services/jd_writer.py", "10 次里 9 次三段齐全", "T3.2", 0.6, "P0", "JM-01"],
    ["T3.5", "Step 3", "技能词典 v1（200+ 条含同义词）", "services/skill_dict.py", "20 种写法都能归一", "T3.1", 0.5, "P0", "SM-01"],
    ["T3.6", "Step 3", "前端职位页（列表/筛选/新建抽屉/审批）", "frontend/app/(dashboard)/jobs", "A1 全流程可点通", "T3.2", 0.9, "P0", "JM-02"],
    ["T3.7", "Step 3", "tests/test_jobs.py 三用例", "backend/tests/test_jobs.py", "非法跳转/越权/缺字段全绿", "T3.2~T3.5", 0.2, "P1", "§8.5"],
    # Step 4
    ["T4.1", "Step 4", "storage.py + 上传白名单/大小限制", "app/services/storage.py", "非法类型 400；路径不含中文", "T3", 0.4, "P0", "RP-01"],
    ["T4.2", "Step 4", "parser.py：PDF→MuPDF→OCR/视觉 降级链", "app/services/parser.py", "6 份样例都能出文本", "T4.1", 1.0, "P0", "RP-01"],
    ["T4.3", "Step 4", "extractor.py：简历 JSON 抽取 + 四层容错", "app/ai/extractor.py", "坏 JSON 也能恢复；字段置信度可用", "T4.2", 1.2, "P0", "RP-02"],
    ["T4.4", "Step 4", "normalize.py：手机/邮箱/日期/学历/技能归一", "app/services/normalize.py", "20 种脏数据归一正确", "T3.5", 0.6, "P0", "RP-02"],
    ["T4.5", "Step 4", "dedupe.py：强键+弱键去重", "app/services/dedupe.py", "同人两份只留 1 条", "T4.4", 0.5, "P1", "RP-03"],
    ["T4.6", "Step 4", "批量上传接口 + 批次进度查询", "api/v1/resumes.py", "100 份上传 <1s 返回批次 id", "T4.1", 0.7, "P0", "RP-05"],
    ["T4.7", "Step 4", "TaskRunner 抽象 + parse_resume 幂等任务", "workers/runner.py、tasks.py", "同文件重复入队只处理一次", "T4.6", 0.7, "P0", "RP-05"],
    ["T4.8", "Step 4", "校对接口 + 上传页/解析结果页", "api + frontend/(dashboard)/resumes", "低置信字段高亮可改", "T4.3", 1.1, "P0", "RP-04"],
    ["T4.9", "Step 4", "tests/test_parser.py 六样例回归", "backend/tests/test_parser.py", "四字段准确率≥90% 有比对表", "T4.2~T4.5", 0.3, "P1", "A2"],
    # Step 5
    ["T5.1", "Step 5", "match_features.py：简历/JD 可比特征", "app/services/match_features.py", "8 类特征齐全且可解释", "T4", 0.8, "P0", "SM-01/02"],
    ["T5.2", "Step 5", "scorer.py：加权公式 + must-have 惩罚", "app/services/scorer.py", "缺 must-have 分数明显更低", "T5.1", 0.9, "P0", "SM-03"],
    ["T5.3", "Step 5", "explain.py：五段理由 + 模板降级", "app/services/explain.py", "LLM 挂了仍出模板理由", "T5.2", 0.7, "P0", "SM-04"],
    ["T5.4", "Step 5", "rank.py：批量评分 + 指纹缓存 + 落库", "app/services/rank.py", "重复请求命中缓存不重算", "T5.2", 0.7, "P0", "SM-03"],
    ["T5.5", "Step 5", "matching.py：/match /matches /feedback", "app/api/v1/matching.py", "三个接口可用且带明细", "T5.4", 0.7, "P0", "SM-03/04"],
    ["T5.6", "Step 5", "eval_match.py + 评测报告 v1", "scripts/eval_match.py、docs/评测-匹配-v1.md", "一致率/Top10 重合/Spearman 有数字", "T0.6,T5.4", 0.6, "P0", "A3"],
    ["T5.7", "Step 5", "前端匹配页（排名表/理由展开/反馈）", "frontend/(dashboard)/matching", "排序筛选反馈全可用", "T5.5", 0.9, "P0", "SM-04"],
    ["T5.8", "Step 5", "tests/test_match.py 五用例", "backend/tests/test_match.py", "排序与分档断言全绿", "T5.2~T5.5", 0.3, "P1", "§8.5"],
    # Step 6
    ["T6.1", "Step 6", "候选人/应聘 schemas + stage_history", "app/schemas/candidate.py", "字段含 source/stage_entered_at", "T5", 0.4, "P0", "RA-03"],
    ["T6.2", "Step 6", "pipeline.py：TRANSITIONS 表 + 校验", "app/services/pipeline.py", "非法边 400 并列出允许目标", "T6.1", 0.6, "P0", "RA-03"],
    ["T6.3", "Step 6", "applications.py：创建/流转/列表/批量", "app/api/v1/applications.py", "每次流转写 history + 审计", "T6.2", 0.7, "P0", "RA-03"],
    ["T6.4", "Step 6", "候选人库检索（关键词/技能/状态）", "api/v1/candidates.py", "按 Python 能命中", "T6.3", 0.5, "P1", "SM-01"],
    ["T6.5", "Step 6", "前端候选人列表/档案/流程看板", "frontend/(dashboard)/candidates", "拖拽改状态走接口", "T6.3", 0.8, "P0", "RA-03"],
    ["T6.6", "Step 6", "tests/test_pipeline.py 四用例", "backend/tests/test_pipeline.py", "6 合法链 + 5 非法边全绿", "T6.2~T6.3", 0.2, "P1", "A5"],
    # Step 7
    ["T7.1", "Step 7", "interview_gen.py：问题集严格 JSON + 兜底", "app/services/interview_gen.py", "schema 合法；6~8 题", "T5", 0.9, "P0", "IA-01"],
    ["T7.2", "Step 7", "评估模板（维度/权重/锚点可配）", "services/interview_templates", "默认模板可用且可改", "T7.1", 0.4, "P1", "IA-02"],
    ["T7.3", "Step 7", "interviews.py：生成/查询/反馈（含缓存）", "app/api/v1/interviews.py", "二次调用 <200ms", "T7.1", 0.6, "P0", "IA-03"],
    ["T7.4", "Step 7", "前端面试准备页 + 记录表单", "frontend/(dashboard)/interviews", "问题可勾选编辑复制", "T7.3", 0.9, "P0", "IA-01"],
    ["T7.5", "Step 7", "tests/test_interview.py 三用例", "backend/tests/test_interview.py", "schema/缓存/越界 422 全绿", "T7.1~T7.3", 0.2, "P1", "A4"],
    # Step 8
    ["T8.1", "Step 8", "notify.py：渠道抽象 + 6 个模板 + 发送记录", "app/services/notify.py", "console 渠道可发且落表", "T6", 0.8, "P0", "RA-01"],
    ["T8.2", "Step 8", "状态流转→模板映射钩子（失败不影响流转）", "services/pipeline + notify", "SMTP 失败仍 200 且有失败记录", "T8.1", 0.5, "P0", "RA-01"],
    ["T8.3", "Step 8", "面试安排 + .ics 生成 + 冲突检测", "api/interviews/schedule", "ICS 可导入；冲突 409", "T8.1", 0.8, "P1", "RA-02"],
    ["T8.4", "Step 8", "SLA 定义 + 定时扫描 + 超时告警", "app/services/sla.py", "超时被标记且可查", "T6.3", 0.7, "P1", "RA-04"],
    ["T8.5", "Step 8", "公开投递页 /careers/{slug} + 匿名提交", "api/careers + frontend", "免登录可投且建申请", "T8.1", 0.9, "P1", "CE-01"],
    ["T8.6", "Step 8", "进度查询（邮箱+编号，限流，不返回分数）", "api/ce/progress", "越权查不到；不泄漏内部字段", "T8.5", 0.5, "P1", "CE-02"],
    ["T8.7", "Step 8", "前端通知中心/排面弹窗/进度页", "frontend/(dashboard)/notifications", "失败可重发", "T8.2", 0.8, "P0", "CE-03"],
    ["T8.8", "Step 8", "tests/test_notify.py 四用例", "backend/tests/test_notify.py", "模板/降级/SLA/匿名全绿", "T8.1~T8.5", 0.3, "P1", "A5"],
    # Step 9
    ["T9.1", "Step 9", "指标口径文档 + analytics.py 聚合函数", "docs/指标口径.md、services/analytics.py", "漏斗/周期/渠道口径可复述", "T6", 0.9, "P0", "DA-01"],
    ["T9.2", "Step 9", "6 个分析接口（dashboard/funnel/cycle/channels/trend/export）", "app/api/v1/analytics.py", "固定数据与手算一致", "T9.1", 0.9, "P0", "DA-01~04"],
    ["T9.3", "Step 9", "Excel 导出（多 sheet + 时间戳）", "services/export.py", "openpyxl 可读、sheet 齐全", "T9.2", 0.5, "P1", "DA-05"],
    ["T9.4", "Step 9", "前端看板（KPI 卡/漏斗/趋势/渠道）", "frontend/(dashboard)/analytics", "首屏≤3s；口径提示可见", "T9.2", 1.0, "P0", "DA-01"],
    ["T9.5", "Step 9", "空态/口径提示/失败重试", "前端组件", "无数据不空白", "T9.4", 0.4, "P2", "G1"],
    ["T9.6", "Step 9", "tests/test_analytics.py 两用例", "backend/tests/test_analytics.py", "20 条造数与手算一致", "T9.1~T9.3", 0.3, "P1", "A6"],
    # Step 10
    ["T10.1", "Step 10", "ai/client.py：分级/超时/重试/JSON/Mock", "app/ai/client.py", "无 Key 时全链路可跑", "T4", 1.0, "P0", "CC-03"],
    ["T10.2", "Step 10", "ai_calls 计量 + pricing 价格表", "services/cost.py、core/pricing.py", "单价×token=金额 一致", "T10.1", 0.6, "P0", "CC-01"],
    ["T10.3", "Step 10", "ai/cache.py：指纹缓存 + 命中率统计", "app/ai/cache.py", "重复输入命中且不计费", "T10.1", 0.6, "P1", "CC-03"],
    ["T10.4", "Step 10", "预算表 + 阈值告警 + 超预算拦截", "services/budget.py", "100% 时新调用被拒", "T10.2", 0.6, "P1", "CC-02"],
    ["T10.5", "Step 10", "cost.py 三个接口（summary/budgets/calls）", "app/api/v1/cost.py", "按职位/用户/功能可分组", "T10.2", 0.6, "P0", "CC-01"],
    ["T10.6", "Step 10", "前端成本页（Admin）", "frontend/(dashboard)/cost", "用量/命中率/预算条可见", "T10.5", 0.7, "P0", "CC-01"],
    ["T10.7", "Step 10", "tests/test_cost.py 三用例", "backend/tests/test_cost.py", "记账/缓存/拦截全绿", "T10.2~T10.5", 0.3, "P1", "CC-02"],
    # Step 11
    ["T11.1", "Step 11", "信息架构：导航分组/面包屑/页签", "frontend/components/layout", "三组导航 + Admin 组可见性正确", "T3~T10", 0.7, "P0", "§8.1"],
    ["T11.2", "Step 11", "设计系统：色阶/表格/卡片/表单提示", "tailwind + globals.css", "分数色阶四档一致", "T11.1", 0.7, "P1", "G1"],
    ["T11.3", "Step 11", "通用组件 7 件套", "frontend/components/*", "各页复用无重复实现", "T11.2", 1.0, "P0", "G1"],
    ["T11.4", "Step 11", "交互细节：loading/乐观更新/未保存提示", "各页面", "异步操作均有 loading", "T11.3", 0.8, "P1", "G1"],
    ["T11.5", "Step 11", "性能：分割/懒加载/虚拟化/skeleton", "各页面", "Lighthouse 首屏≤3s", "T11.3", 0.8, "P0", "G1"],
    ["T11.6", "Step 11", "兼容与响应式（三浏览器 + 1366 宽）", "样式与布局", "G3 三浏览器主流程可用", "T11.4", 0.6, "P1", "G3"],
    ["T11.7", "Step 11", "空/错/载三态全量走查 + 截图", "docs/assets/三态", "每页三态留档", "T11.4", 0.4, "P2", "G1"],
    # Step 12
    ["T12.1", "Step 12", "安全响应头 + CORS 收紧 + HTTPS 说明", "middleware + docs", "头齐全；生产 CORS 白名单", "S2", 0.4, "P0", "§10.2"],
    ["T12.2", "Step 12", "PII 字段 Fernet 加密存储", "core/security + models", "库里看不到明文手机号", "T12.1", 0.8, "P0", "§10.2"],
    ["T12.3", "Step 12", "列表脱敏 + 查看完整信息二次确认", "api + 前端", "列表 138****；确认后写审计", "T12.2", 0.6, "P0", "§10.2"],
    ["T12.4", "Step 12", "审计覆盖（查看/导出/删除/改角色）", "services/audit", "4 类动作可追溯", "T12.3", 0.4, "P0", "§10.2"],
    ["T12.5", "Step 12", "限流（全局 100/min + 敏感接口更严）", "core/rate_limit.py", "超限 429 带 Retry-After", "T12.1", 0.6, "P1", "§8.3"],
    ["T12.6", "Step 12", "删除权接口 + 删除证明导出", "api/candidates/delete-pii", "删除后 PII 不可读且留审计", "T12.2", 0.6, "P1", "§10.2"],
    ["T12.7", "Step 12", "OWASP 自查表 + 日志脱敏中间件", "docs/安全自查表.md", "10 项均有结论与证据", "T12.1~T12.5", 0.5, "P0", "G4"],
    ["T12.8", "Step 12", "tests/test_rbac.py 18 条越权断言", "backend/tests/test_rbac.py", "18 条全绿（越权返回 404）", "T12.3", 0.4, "P1", "G4"],
    # Step 13
    ["T13.1", "Step 13", "pytest 基建 + conftest（临时库/客户端/Mock）", "backend/tests/conftest.py", "一条命令跑全量测试", "S1", 0.5, "P0", "§8.5"],
    ["T13.2", "Step 13", "八模块覆盖率补到 ≥80%", "backend/tests/*", "pytest --cov 报告达标", "T13.1", 1.2, "P0", "§8.5"],
    ["T13.3", "Step 13", "P0 接口契约测试（happy+错误路径）", "tests/test_contract.py", "每个 P0 接口≥2 条", "T13.1", 0.8, "P1", "§8.5"],
    ["T13.4", "Step 13", "评测回归脚本（解析/匹配基线对比）", "scripts/eval_*.py", "退化时脚本非 0 退出", "T5.6", 0.5, "P0", "A3"],
    ["T13.5", "Step 13", "前端 vitest（工具函数 + 2 组件）", "frontend tests", "2 个组件断言通过", "T11", 0.4, "P2", "§8.5"],
    ["T13.6", "Step 13", "smoke.ps1 端到端冒烟", "scripts/smoke.ps1", "建职位→传简历→匹配→流转 一条命令跑通", "T13.1", 0.4, "P0", "A1~A5"],
    ["T13.7", "Step 13", "测试报告（覆盖率/未覆盖原因/已知缺陷）", "docs/测试报告.md", "缺口有解释", "T13.2", 0.2, "P1", "§8.5"],
    # Step 14
    ["T14.1", "Step 14", "docker-compose（api/worker/web/pg/redis）", "docker-compose.yml", "语法校验通过、服务定义齐全", "全部", 0.6, "P1", "§9.3"],
    ["T14.2", "Step 14", "start-dev/start-prod 脚本 + 默认账号提示", "scripts/*.ps1", "干净目录按脚本可起", "T14.1", 0.5, "P0", "§9.3"],
    ["T14.3", "Step 14", ".env.example 注释 + 部署文档（10 条故障）", "docs/部署文档.md", "照文档 15 分钟可跑", "T14.2", 0.8, "P0", "G5"],
    ["T14.4", "Step 14", "API 文档（OpenAPI 导出 + curl 示例 + 错误码）", "docs/API文档.md", "关键接口示例可复制执行", "T14.3", 0.6, "P0", "G5"],
    ["T14.5", "Step 14", "用户手册（三角色分册）", "docs/用户手册.md", "三角色各一条主流程", "T14.3", 0.7, "P0", "G5"],
    ["T14.6", "Step 14", "seed.py 固定演示数据集", "scripts/seed.py", "1 公司/3 账号/3 职位/10 简历/20 申请", "T14.2", 0.5, "P0", "§11"],
    ["T14.7", "Step 14", "备份与恢复脚本 + 说明", "scripts/backup.ps1", "备份可恢复出同样数据", "T14.2", 0.3, "P2", "§8.2"],
    # Step 15
    ["T15.1", "Step 15", "验收报告逐条填 A1~A6 + G1~G5", "docs/验收报告.md", "11 条均有判据与证据", "全部", 0.8, "P0", "§14"],
    ["T15.2", "Step 15", "KPI 实测（解析/匹配/批量/首屏/P50）", "docs/KPI实测.md", "全部为数字且可复现", "T13.4", 0.7, "P0", "§3.3"],
    ["T15.3", "Step 15", "演示脚本 + 空跑一遍", "docs/演示脚本.md", "≤8 分钟不卡壳", "T15.1", 0.5, "P0", "§14"],
    ["T15.4", "Step 15", "演示数据与 8 张关键截图", "docs/assets/", "固定账号与数据集可复现", "T14.6", 0.4, "P1", "§14"],
    ["T15.5", "Step 15", "known issues（Phase2 五项 + 已知缺陷）", "docs/known-issues.md", "5 项标不实现、缺陷有规避", "T15.1", 0.3, "P1", "§3.2"],
    ["T15.6", "Step 15", "答辩 Q&A 预案（10 问）", "docs/Q&A.md", "10 问均有数字或口径", "T15.2", 0.3, "P1", "§14"],
]

REQS = [
    ["UC-01", "邮箱注册", "P0", "S2"], ["UC-02", "邮箱登录", "P0", "S2"], ["UC-03", "密码重置", "P0", "S2"],
    ["UC-04", "个人信息管理", "P1", "S2/S11"], ["UC-05", "API Key 管理", "P0", "S2"], ["UC-06", "用户列表管理", "P1", "S2"],
    ["JM-01", "职位创建（AI 辅助 JD）", "P0", "S3"], ["JM-02", "职位列表与筛选", "P0", "S3"], ["JM-03", "职位审批", "P1", "S3"],
    ["JM-04", "职位归档", "P1", "S3"], ["JM-05", "职位模板", "P2", "不实现"],
    ["RP-01", "多格式解析", "P0", "S4"], ["RP-02", "信息提取", "P0", "S4"], ["RP-03", "简历去重", "P1", "S4"],
    ["RP-04", "解析结果校对", "P1", "S4"], ["RP-05", "批量解析", "P0", "S4"],
    ["SM-01", "技能匹配", "P0", "S5"], ["SM-02", "经验匹配", "P0", "S5"], ["SM-03", "综合评分与排名", "P0", "S5"],
    ["SM-04", "匹配理由", "P1", "S5"], ["SM-05", "人才库推荐", "P2", "不实现"],
    ["IA-01", "面试问题生成", "P0", "S7"], ["IA-02", "评估模板", "P1", "S7"], ["IA-03", "面试记录", "P1", "S7"],
    ["IA-04", "面试报告", "P2", "不实现"],
    ["RA-01", "自动通知", "P0", "S8"], ["RA-02", "面试安排", "P1", "S8"], ["RA-03", "流程状态管理", "P0", "S6"],
    ["RA-04", "SLA 监控", "P1", "S8"],
    ["DA-01", "招聘看板", "P0", "S9"], ["DA-02", "渠道分析", "P1", "S9"], ["DA-03", "周期分析", "P1", "S9"],
    ["DA-04", "成本分析", "P1", "S9/S10"], ["DA-05", "报表导出", "P1", "S9"],
    ["CE-01", "个性化投递页", "P1", "S8"], ["CE-02", "进度查询", "P1", "S8"], ["CE-03", "自动反馈", "P1", "S8"],
    ["CE-04", "满意度调查", "P2", "不实现"],
    ["CC-01", "Token 用量统计", "P0", "S10"], ["CC-02", "成本预算", "P1", "S10"], ["CC-03", "优化策略", "P1", "S10"],
    ["CC-04", "成本报表", "P2", "不实现"],
]

ACCEPT = [
    ["A1", "职位管理全流程", "创建/编辑/发布/归档可用", "S3", "4 条接口记录 + 状态流转日志 + 录屏"],
    ["A2", "简历解析", "PDF/Word/JPG/PNG 解析，准确率≥90%", "S4", "6 份样例四字段比对表（数字）"],
    ["A3", "人岗匹配", "与 HR 评估一致性≥80%", "S5", "30 条标注集：一致率/Top10 重合/Spearman"],
    ["A4", "AI 面试辅助", "基于 JD 与简历生成个性化问题", "S7", "10 个职位生成结果 + 引用具体经历抽检"],
    ["A5", "招聘流程", "状态流转与自动通知正常", "S6/S8", "4 类主流程通知记录（模板/渠道/时间）"],
    ["A6", "数据分析", "看板 KPI 准确", "S9", "固定数据集与手算对照表 + 截图"],
    ["G1", "页面性能", "首屏≤3 秒", "S11", "Lighthouse 关键 4 页报告"],
    ["G2", "API 性能", "P50≤300ms", "S12/S13", "100 并发 1 分钟压测分位表"],
    ["G3", "兼容性", "Chrome/Firefox/Edge 近两版", "S11", "三浏览器主流程截图"],
    ["G4", "安全性", "OWASP Top10 基础测试", "S12", "自查表 + 18 条越权断言 + 限流/脱敏证据"],
    ["G5", "文档完整性", "API/用户/部署三份文档", "S14", "三份文档 + 15 分钟部署实录"],
]

RISKS = [
    ["R1", "解析准确率不达标", "样例四字段<90%", "A2 挂", "多解析器链 + 视觉 LLM 兜底 + 人工校对"],
    ["R2", "匹配与 HR 判断不一致", "一致率<80%", "A3 挂", "权重可配 + 标注集调参 + 反馈回流"],
    ["R3", "候选人隐私泄漏", "日志出现明文手机号", "合规事故", "日志脱敏 + 字段加密 + 访问审计"],
    ["R4", "批量解析超时", "100 份>10 分钟", "演示失败", "并发可配 + 进度可查 + 失败重试"],
    ["R5", "LLM 结构漂移", "前端渲染崩", "功能不可用", "schema 校验 + 修复重试 + 模板兜底"],
    ["R6", "Token 成本超预算", "单月>500 元", "账单失控", "分级 + 缓存 + 预算拦截 + 用量页"],
    ["R7", "Redis 未装", "Celery 起不来", "队列不可用", "QUEUE_MODE 切内存；演示前装 Memurai"],
    ["R8", "PostgreSQL 起不来", "迁移失败", "无法演示", "开发 SQLite；演示前 3 天切 PG 回归"],
    ["R9", "状态机被绕过", "库里出现 new→offer", "数据不可信", "只暴露 transition 接口 + 服务端校验 + 审计"],
    ["R10", "范围蔓延", "开始做视频面试/画像", "延期", "需求基线中 Phase2 项标「不实现」"],
    ["R11", "AI 偏见", "某群体系统性低分", "伦理质疑", "不采集性别/年龄/婚育；抽样群体均分对照"],
    ["R12", "单人项目进度崩", "连续两周 DoD 未达", "交不出", "砍到 A 线闭环，先保能演示"],
]

# ---- 9 阶段计划（2026-11-19 重写：白话版，照着做） ----
CORE_STEPS = [
    ["1", "环境 + 数据库空壳", "装依赖、建目录、9 张表、/healthz、空白首页", 2.5, "打开 /docs 有接口、首页有页面、库里 9 张表", "登录、职位、简历（只有空壳）"],
    ["2", "登录和三种角色", "注册/登录/JWT/3 个演示账号/路由守卫/角色菜单", 2.5, "三个账号能登录、菜单不同、不登录进不去", "邮箱验证、找回密码、API Key"],
    ["3", "建职位", "职位 CRUD/发布/技能词表/AI 生成 JD/职位页", 3, "建职位+AI 生成 JD+发布成功", "多级审批、职位模板"],
    ["4", "上传简历并解析", "多文件上传/PDF+Word 解析/大模型抽取/清洗/去重/校对页", 5, "传 PDF/Word 出结构化、能改、同人去重", "100 份压测、重试队列"],
    ["5", "匹配打分", "特征/评分公式/理由/批量+缓存/排名页/一致率评测", 5, "出排名+理由、一致率有数字", "人才库推荐、多组权重"],
    ["6", "候选人流程", "状态机/历史记录/候选人档案/看板/站内通知", 3, "拖状态、非法跳转被拒、有历史", "邮件、日历、SLA、投递页"],
    ["7", "AI 面试题", "生成 6~8 题+考察点/缓存/展示页", 2, "8 道题、≥5 道引用具体经历", "评分表、面试记录"],
    ["8", "数据看板", "4 个指标/漏斗/渠道/一页图表", 3, "4 数字+漏斗+渠道、与库一致", "导出、成本分析、趋势"],
    ["9", "收尾能演示", "seed 数据/README/一条命令启动/演示脚本/实测数字", 2.5, "造数据、一条命令起、5 分钟演示", "Docker、三件套文档"],
]

STEP_CORE = {
    "Step 0": "必做", "Step 1": "必做", "Step 2": "必做", "Step 3": "必做",
    "Step 4": "必做", "Step 5": "必做", "Step 6": "必做", "Step 7": "必做",
    "Step 8": "部分", "Step 9": "必做", "Step 10": "扩展", "Step 11": "扩展",
    "Step 12": "扩展", "Step 13": "扩展", "Step 14": "扩展", "Step 15": "扩展",
}

STEP_M = {
    "Step 0": "阶段1", "Step 1": "阶段1", "Step 2": "阶段2", "Step 3": "阶段3",
    "Step 4": "阶段4", "Step 5": "阶段5", "Step 6": "阶段6", "Step 7": "阶段7",
    "Step 8": "阶段6", "Step 9": "阶段8",
}

TASK_CORE = {
    "T2.6": "可选", "T2.7": "可选", "T3.3": "必做", "T6.4": "可选",
    "T7.2": "扩展", "T8.3": "扩展", "T8.4": "扩展", "T8.5": "扩展",
    "T8.6": "扩展", "T9.3": "扩展", "T13.1": "扩展",
}


def task_core(task_id, step):
    return TASK_CORE.get(task_id, STEP_CORE.get(step, "扩展"))


def task_m(task_id, step):
    return STEP_M.get(step, "扩展")


REQ_CORE = {}
for _k in ["UC-01", "UC-02", "JM-01", "JM-02", "JM-04", "RP-01", "RP-02", "RP-03", "RP-04", "RP-05",
           "SM-01", "SM-02", "SM-03", "SM-04", "IA-01", "RA-01", "RA-03", "DA-01", "DA-03"]:
    REQ_CORE[_k] = "必做"
for _k in ["UC-06", "JM-03", "DA-02", "CC-01", "CC-03"]:
    REQ_CORE[_k] = "简版"
for _k in ["UC-03", "UC-04", "UC-05", "IA-02", "IA-03", "RA-02", "RA-04", "DA-04", "DA-05",
           "CE-01", "CE-02", "CE-03", "CC-02"]:
    REQ_CORE[_k] = "延后"
for _k in ["JM-05", "SM-05", "IA-04", "CE-04", "CC-04"]:
    REQ_CORE[_k] = "不做"


def style_sheet(ws, headers, widths, title, tab_color):
    ws.sheet_properties.tabColor = tab_color
    ws.freeze_panes = "A3"
    ws["A1"] = title
    ws["A1"].font = TITLE_FONT
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
    ws.row_dimensions[1].height = 24
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=2, column=i, value=h)
        c.fill = HEAD_FILL
        c.font = HEAD_FONT
        c.alignment = CENTER
        c.border = BORDER
        ws.column_dimensions[get_column_letter(i)].width = widths[i - 1]
    ws.row_dimensions[2].height = 28
    ws.auto_filter.ref = "A2:%s%d" % (get_column_letter(len(headers)), 2 + 1000)


def fill_rows(ws, rows, start=3, sprint_col=None):
    for r, row in enumerate(rows, start=start):
        for c, val in enumerate(row, start=1):
            cell = ws.cell(row=r, column=c, value=val)
            cell.border = BORDER
            cell.alignment = CENTER if len(str(val)) <= 8 else WRAP
        if sprint_col:
            key = str(row[sprint_col - 1])
            if key in SPRINT_FILL:
                for c in range(1, len(row) + 1):
                    ws.cell(row=r, column=c).fill = PatternFill("solid", fgColor=SPRINT_FILL[key])


wb = Workbook()

# ---- Sheet 0 阶段计划（照着做） ----
ws = wb.active
ws.title = "0.阶段计划"
headers = ["阶段", "名称", "要干的事（摘要）", "人日", "做完你怎么确认", "这阶段不做什么"]
style_sheet(ws, headers, [6, 20, 46, 7, 44, 30],
            "9 个阶段（28.5 人日 / 6 周）—— 照着做就行", "C00000")
fill_rows(ws, CORE_STEPS)
total_core = sum(r[3] for r in CORE_STEPS)
ws.cell(row=len(CORE_STEPS) + 4, column=1, value="合计").font = Font(bold=True)
ws.cell(row=len(CORE_STEPS) + 4, column=2, value="%s 人日 ≈ 6 周全职（课余 ×2 ≈ 12 周）" % total_core).font = Font(bold=True)
ws.cell(row=len(CORE_STEPS) + 5, column=2,
        value="只剩 3 周：做阶段 1~5 + 阶段 9 简版（只造数据写 README），阶段 6~8 后补").font = Font(color="C00000")
ws.cell(row=len(CORE_STEPS) + 6, column=2,
        value="每阶段结束必须能跑；每阶段至少 2 条测试；每阶段一次 git 提交").font = Font(color="808080")

# ---- Sheet 1 总览 ----
ws = wb.create_sheet("0.总览")
headers = ["Step", "名称", "Sprint", "人日", "依赖", "主要产出", "完成标准(DoD)", "里程碑", "PRD", "阶段"]
style_sheet(ws, headers, [9, 24, 10, 7, 10, 46, 40, 10, 22, 9],
            "完整版 16 步总览（68 人日；最后一列告诉你它属于哪个阶段）", "1F3864")
fill_rows(ws, [s + [STEP_M.get(s[0], "扩展")] for s in STEPS], sprint_col=3)
total = sum(x[3] for x in STEPS if isinstance(x[3], (int, float)))
ws.cell(row=len(STEPS) + 4, column=1, value="合计").font = Font(bold=True)
ws.cell(row=len(STEPS) + 4, column=2, value="Step 0~15 合计 %d 人日" % total).font = Font(bold=True)
ws.cell(row=len(STEPS) + 5, column=2,
        value="时间线：A 最快闭环 30 人日（S0~S5+S9 简版）/ B 答辩交付 52 人日 / C 完整 Phase1 68 人日").font = Font(color="C00000")
ws.cell(row=len(STEPS) + 6, column=2,
        value="课余开发把总人日 ×1.8~2.2；排期以本页为准，拆分以任务清单为准").font = Font(color="808080")

# ---- Sheet 2 任务清单 ----
ws = wb.create_sheet("1.任务清单")
headers = ["任务编号", "Step", "任务内容", "交付物", "完成标准(DoD)", "依赖", "人日", "优先级", "PRD", "核心版", "阶段", "状态", "负责人", "备注"]
style_sheet(ws, headers, [9, 9, 46, 34, 40, 14, 6, 7, 18, 8, 10, 10, 10, 20],
            "任务清单（%d 条；核心版列＝必做/部分/可选/扩展，可勾选跟踪）" % len(TASKS), "2E75B6")
rows = [t + [task_core(t[0], t[1]), task_m(t[0], t[1]), "未开始", "", ""] for t in TASKS]
fill_rows(ws, rows)
dv = DataValidation(type="list", formula1='"未开始,进行中,已完成,阻塞,已取消"', allow_blank=True)
ws.add_data_validation(dv)
dv.add("L3:L%d" % (len(rows) + 2))
for r in range(3, len(rows) + 3):
    ws.cell(row=r, column=12).alignment = CENTER

# ---- Sheet 3 需求追溯 ----
ws = wb.create_sheet("2.需求追溯")
headers = ["需求编号", "需求名称", "优先级", "实现步骤", "核心版", "状态", "证据链接/说明"]
style_sheet(ws, headers, [12, 30, 8, 14, 8, 10, 46], "PRD 42 项功能需求追溯矩阵（含核心版取舍）", "548235")
rows = [[r[0], r[1], r[2], r[3], REQ_CORE.get(r[0], ""), "TODO", ""] for r in REQS]
fill_rows(ws, rows)
dv2 = DataValidation(type="list", formula1='"TODO,进行中,已完成,不实现,延后"', allow_blank=True)
ws.add_data_validation(dv2)
dv2.add("F3:F%d" % (len(rows) + 2))
for r in range(3, len(rows) + 3):
    ws.cell(row=r, column=6).alignment = CENTER
ws.cell(row=len(rows) + 4, column=1, value="覆盖自查").font = Font(bold=True)
ws.cell(row=len(rows) + 4, column=2,
        value="Phase1 共 37 项 ｜ 核心版：19 必做 + 5 简版 = 24 / 37 ｜ 13 项延后 ｜ Phase2 五项标「不做」").font = Font(bold=True, color="C00000")

# ---- Sheet 4 验收清单 ----
ws = wb.create_sheet("3.验收清单")
headers = ["编号", "验收项", "判据", "产出步骤", "证据形式", "结论"]
style_sheet(ws, headers, [8, 22, 42, 14, 44, 10], "PRD §14 验收清单（答辩逐条对）", "BF8F00")
rows = [a + [""] for a in ACCEPT]
fill_rows(ws, rows)
dv3 = DataValidation(type="list", formula1='"通过,不通过,待测"', allow_blank=True)
ws.add_data_validation(dv3)
dv3.add("F3:F%d" % (len(rows) + 2))
for r in range(3, len(rows) + 3):
    ws.cell(row=r, column=6).alignment = CENTER

# ---- Sheet 5 风险清单 ----
ws = wb.create_sheet("4.风险清单")
headers = ["编号", "风险", "触发信号", "影响", "应对措施（写进代码）", "状态"]
style_sheet(ws, headers, [8, 24, 24, 16, 48, 10], "风险与降级措施（不能只写在文档里）", "C00000")
rows = [r + [""] for r in RISKS]
fill_rows(ws, rows)
dv4 = DataValidation(type="list", formula1='"未发生,已缓解,已发生"', allow_blank=True)
ws.add_data_validation(dv4)
dv4.add("F3:F%d" % (len(rows) + 2))

# ---- Sheet 6 说明 ----
ws = wb.create_sheet("5.使用说明")
ws.sheet_properties.tabColor = "808080"
ws["A1"] = "使用说明"
ws["A1"].font = TITLE_FONT
lines = [
    "0. 「0.阶段计划」是照着做的 9 个阶段（28.5 人日 / 6 周）：只剩 3 周时做阶段 1~5 + 阶段 9 简版。",
    "1. 「0.总览」是完整版 16 步（68 人日）参考；最后一列「阶段」告诉你这步属于哪个阶段，「扩展」= 以后再补。",
    "2. 「1.任务清单」是执行层：按「核心版」列筛选「必做/部分」，本周要做的状态改「进行中」，完成后改「已完成」并填负责人。",
    "3. 「2.需求追溯」是验收层：每完成一项填证据（截图路径 / 接口记录 / 测试报告），答辩按它对。",
    "4. 「3.验收清单」对应 PRD §14：A1~A6 是 Phase1 功能验收，G1~G5 是通用验收；结论只有通过/不通过/待测。",
    "5. 「4.风险清单」的应对措施必须写进代码（降级开关、超时、幂等、脱敏），只写文档等于没有。",
    "",
    "关键约束（来自 PRD）：Phase1 共 37 项；Phase2 的 JM-05 / SM-05 / IA-04 / CE-04 / CC-04 明确不实现。",
    "三条 KPI 决定必须有评测集：解析准确率≥90%、匹配一致率≥80%、招聘周期缩短≥30%（都需要标注集与脚本证明）。",
    "",
    "时间线：A 最快闭环（约 4 周，30 人日）→ B 答辩交付（约 10 周，52 人日）→ C 完整 Phase1（约 14 周，68 人日）。",
    "课余开发请把总人日 ×1.8~2.2。",
    "",
    "详细做法见同目录的 TalentMatch_分步实施路线图_V1.md（每步含 目标/前置/任务/产出/DoD/坑/PRD）。",
    "",
    "口径说明：总览页人日是步骤级（含联调与演示准备）；任务清单是 0.5~1 天粒度细估，合计略高于总览（缓冲）。",
]
for i, line in enumerate(lines, start=3):
    ws.cell(row=i, column=1, value=line).font = Font(size=11)
ws.column_dimensions["A"].width = 120

for s in wb.worksheets:
    s.sheet_view.showGridLines = False

wb.save(OUT)
print("saved:", OUT)
print("core_steps:", len(CORE_STEPS), "core_days:", sum(r[3] for r in CORE_STEPS))
print("steps:", len(STEPS), "tasks:", len(TASKS), "reqs:", len(REQS), "accept:", len(ACCEPT), "risks:", len(RISKS))
print("task_days:", sum(t[6] for t in TASKS), "step_days:", sum(s[3] for s in STEPS))
print("core_tasks:", sum(1 for t in TASKS if task_core(t[0], t[1]) == "必做"),
      "core_task_days:", sum(t[6] for t in TASKS if task_core(t[0], t[1]) == "必做"))
