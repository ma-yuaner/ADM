from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


DEFAULT_COLUMNS = [
    {"key": "admNo", "label": "ADM单号"},
    {"key": "otaCode", "label": "数据源"},
    {"key": "otaOrderNo", "label": "OTA订单号"},
    {"key": "airline", "label": "航司"},
    {"key": "ticketNo", "label": "票号"},
    {"key": "ticketCount", "label": "票号数量"},
    {"key": "amount", "label": "ADM金额"},
    {"key": "currency", "label": "币种"},
    {"key": "supplyIssueDate", "label": "供应下发日期"},
    {"key": "deadline", "label": "申诉截止时间"},
    {"key": "stageName", "label": "当前阶段"},
    {"key": "alertText", "label": "预警"},
    {"key": "owner", "label": "责任人"},
    {"key": "actualOwner", "label": "实际处理人"},
]


def _safe_sheet_name(value: str) -> str:
    value = re.sub(r"[\\/*?:\[\]]", "_", value or "未配置")
    return value[:31] or "未配置"


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

    def _columns_for(self, source: str) -> list[dict]:
        return self.profiles.get(source, self.profiles["DEFAULT"]).get("columns", DEFAULT_COLUMNS)

    @staticmethod
    def _cell_value(value):
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return value
        return "" if value is None else value

    def build(self, tasks: list[dict]) -> BytesIO:
        workbook = Workbook()
        workbook.remove(workbook.active)
        groups: dict[str, list[dict]] = defaultdict(list)
        for task in tasks:
            groups[task.get("otaCode") or "未配置"].append(task)
        if not groups:
            groups["无数据"] = []

        used_names: set[str] = set()
        for source, items in sorted(groups.items()):
            name = _safe_sheet_name(source)
            base, counter = name, 2
            while name in used_names:
                suffix = f"_{counter}"
                name = f"{base[:31-len(suffix)]}{suffix}"
                counter += 1
            used_names.add(name)
            sheet = workbook.create_sheet(name)
            columns = self._columns_for(source)
            sheet.append([column["label"] for column in columns])
            for cell in sheet[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="2457D6")
                cell.alignment = Alignment(horizontal="center", vertical="center")

            for item in items:
                sheet.append([self._cell_value(item.get(column["key"])) for column in columns])

            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for column_index, column in enumerate(columns, start=1):
                values = [str(column["label"])] + [str(item.get(column["key"], "") or "") for item in items[:300]]
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
