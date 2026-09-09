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
    {"key": "ticketNo", "label": "票号"},
    {"key": "amount", "label": "ADM总金额（冗余汇总，= SUM(adm_details.amount)，方便列表排序展示）"},
    {"key": "currency", "label": "主币种（CNY/USD/EUR等，明细行可不同币种时以明细为准）"},
    {"key": "supplyIssueDate", "label": "供应下发日期"},
    {"key": "deadline", "label": "ADM最晚时限（回复截至时间）"},
    {"key": "differenceDescription", "label": "差异说明"},
    {"key": "owner", "label": "当前责任人（处理人，中间可转手，历史记录见flow_logs）"},
    {"key": "confirmation", "label": "是否确认（部分不是我们的订单供应发错了/或者资料不齐全）"},
    {"key": "actualOwner", "label": "实际责任人"},
    {"key": "handlingProgress", "label": "处理进度（是否录入差异）"},
    {"key": "appealSubmissionStatus", "label": "申诉状态(已提交/待提交/不提交可结案)"},
    {"key": "appealReason", "label": "申诉原因（status=申诉时必填）"},
    {"key": "appealResultName", "label": "申诉结果"},
    {"key": "resolution", "label": "结案处理结果（status=已结案时必填，如：已退款¥XXX / 差异已消化 / 关单无差异等）"},
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

            for row in sheet.iter_rows(min_row=2):
                for cell in row:
                    cell.alignment = Alignment(vertical="top", wrap_text=True)

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
