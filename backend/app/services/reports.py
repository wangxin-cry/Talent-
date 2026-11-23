"""
招聘报表导出（PRD DA-05）

把看板数据写成单文件 Excel：总览 / 漏斗 / 渠道 / 周期 / SLA。
数据全部来自 analytics 服务，与页面展示口径一致。
"""
from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import analytics as analytics_svc

_HEADER_FILL = PatternFill("solid", fgColor="DCE4FF")
_HEADER_FONT = Font(bold=True)
_TITLE_FONT = Font(bold=True, size=14)


def _header(ws, row: int, values: list[str]) -> None:
    for col, value in enumerate(values, start=1):
        cell = ws.cell(row=row, column=col, value=value)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center")


def _autosize(ws) -> None:
    for column in ws.columns:
        width = 10
        for cell in column:
            text = "" if cell.value is None else str(cell.value)
            width = max(width, min(40, len(text) * 2 + 2))
        ws.column_dimensions[column[0].column_letter].width = width


async def build_workbook(db: AsyncSession) -> bytes:
    """生成招聘数据报表（xlsx 字节流）"""
    dashboard = await analytics_svc.dashboard(db)
    sla = await analytics_svc.sla(db)

    wb = Workbook()

    # ---------------- 总览 ----------------
    ws = wb.active
    ws.title = "总览"
    ws["A1"] = "TalentMatch 招聘数据报表"
    ws["A1"].font = _TITLE_FONT
    ws["A2"] = f"生成时间：{dashboard['generated_at']:%Y-%m-%d %H:%M:%S}"
    overview = dashboard["overview"]
    rows = [
        ("在招职位", overview["open_jobs"]),
        ("累计投递", overview["total_applications"]),
        ("待面试", overview["pending_interview"]),
        ("已入职", overview["hired"]),
        ("已淘汰", overview["rejected"]),
        ("平均招聘周期（天）", overview["avg_cycle_days"] or "-"),
        ("SLA 超时记录", sla["total"]),
    ]
    _header(ws, 4, ["指标", "数值"])
    for index, (name, value) in enumerate(rows, start=5):
        ws.cell(row=index, column=1, value=name)
        ws.cell(row=index, column=2, value=value)
    _autosize(ws)

    # ---------------- 漏斗 ----------------
    ws = wb.create_sheet("漏斗")
    _header(ws, 1, ["阶段", "到达人数", "当前停留", "占比", "阶段转化率"])
    for row_index, item in enumerate(dashboard["funnel"], start=2):
        ws.cell(row=row_index, column=1, value=item["label"])
        ws.cell(row=row_index, column=2, value=item["count"])
        ws.cell(row=row_index, column=3, value=item["current"])
        ws.cell(row=row_index, column=4, value=item["share"])
        ws.cell(row=row_index, column=5, value=item["conversion"])
    _autosize(ws)

    # ---------------- 渠道 ----------------
    ws = wb.create_sheet("渠道")
    _header(ws, 1, ["渠道", "投递", "进入面试", "入职", "淘汰", "入职转化率"])
    for row_index, item in enumerate(dashboard["channels"], start=2):
        ws.cell(row=row_index, column=1, value=item["source"])
        ws.cell(row=row_index, column=2, value=item["total"])
        ws.cell(row=row_index, column=3, value=item["interview"])
        ws.cell(row=row_index, column=4, value=item["hired"])
        ws.cell(row=row_index, column=5, value=item["rejected"])
        ws.cell(row=row_index, column=6, value=item["conversion"])
    _autosize(ws)

    # ---------------- 周期 ----------------
    ws = wb.create_sheet("周期")
    _header(ws, 1, ["阶段", "样本数", "平均停留（小时）"])
    for row_index, item in enumerate(dashboard["cycle"], start=2):
        ws.cell(row=row_index, column=1, value=item["label"])
        ws.cell(row=row_index, column=2, value=item["samples"])
        ws.cell(row=row_index, column=3, value=item["avg_hours"])
    _autosize(ws)

    # ---------------- SLA ----------------
    ws = wb.create_sheet("SLA超时")
    _header(ws, 1, ["职位", "候选人", "当前阶段", "停留（小时）", "阈值（小时）", "超时（小时）"])
    for row_index, item in enumerate(sla["items"], start=2):
        ws.cell(row=row_index, column=1, value=item["job_title"])
        ws.cell(row=row_index, column=2, value=item["candidate_name"])
        ws.cell(row=row_index, column=3, value=item["status_label"])
        ws.cell(row=row_index, column=4, value=item["hours_in_stage"])
        ws.cell(row=row_index, column=5, value=item["limit_hours"])
        ws.cell(row=row_index, column=6, value=item["overdue_hours"])
    _autosize(ws)

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
