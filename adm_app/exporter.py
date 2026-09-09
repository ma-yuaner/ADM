from __future__ import annotations

import json
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


DEFAULT_COLUMNS = [
    {"key": "admNo", "label": "ADM单号"},
    {"key": "otaCode", "label": "平台"},
    {"key": "airline", "label": "航司"},
    {"key": "stageName", "label": "当前阶段"},
    {"key": "ticketNo", "label": "票号"},
    {"key": "amount", "label": "ADM总金额"},
    {"key": "currency", "label": "主币种"},
    {"key": "supplyIssueDate", "label": "供应下发日期"},
    {"key": "deadline", "label": "ADM最晚时限"},
    {"key": "differenceDescription", "label": "差异说明"},
    {"key": "owner", "label": "当前责任人"},
    {"key": "confirmation", "label": "是否确认"},
    {"key": "actualOwner", "label": "实际责任人"},
    {"key": "handlingProgress", "label": "处理进度"},
    {"key": "appealSubmissionStatus", "label": "申诉状态"},
    {"key": "appealReason", "label": "申诉原因"},
    {"key": "appealResultName", "label": "申诉结果"},
    {"key": "resolution", "label": "结案处理结果"},
]


class ExcelExportService:
    def __init__(self, profiles_file: Path):
        self.profiles_file = profiles_file
        self.profiles = self._load_profiles()

    def _load_profiles(self) -> dict:
        if not self.profiles_file.exists():
            return {"DEFAULT": {"columns": DEFAULT_COLUMNS}}
        with self.profiles_file.open("r", encoding="utf-8") as handle:
            configured = json.load(handle)
        configured.setdefault("DEFAULT", {"columns": DEFAULT_COLUMNS})
        return configured

    def _columns(self) -> list[dict]:
        return self.profiles["DEFAULT"].get("columns", DEFAULT_COLUMNS)

    @staticmethod
    def _cell_value(value):
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return value
        return "" if value is None else value

    def build(self, tasks: list[dict]) -> BytesIO:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "ADM待处理"
        columns = self._columns()
        sheet.append([column["label"] for column in columns])
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="2457D6")
            cell.alignment = Alignment(horizontal="center", vertical="center")

        for item in tasks:
            sheet.append([self._cell_value(item.get(column["key"])) for column in columns])

        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(vertical="top", wrap_text=True)

        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for column_index, column in enumerate(columns, start=1):
            values = [str(column["label"])] + [str(item.get(column["key"], "") or "") for item in tasks[:300]]
            width = min(max(max(map(len, values)) + 2, 10), 36)
            sheet.column_dimensions[get_column_letter(column_index)].width = width
            key = column["key"]
            if key in {"deadline", "updateTime"}:
                for cell in sheet.iter_cols(min_col=column_index, max_col=column_index, min_row=2):
                    cell[0].number_format = "yyyy-mm-dd hh:mm"
            elif key == "supplyIssueDate":
                for cell in sheet.iter_cols(min_col=column_index, max_col=column_index, min_row=2):
                    cell[0].number_format = "yyyy-mm-dd"
            elif key == "amount":
                for cell in sheet.iter_cols(min_col=column_index, max_col=column_index, min_row=2):
                    cell[0].number_format = "#,##0.00"

        stream = BytesIO()
        workbook.save(stream)
        stream.seek(0)
        return stream
