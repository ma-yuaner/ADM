from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from .errors import AppError


PERSON_SEPARATOR = re.compile(r"[、,，/;；]+")
IGNORED_PERSON_MARKERS = {"", "已离职", "离职", "无", "未配置"}


def _clean(value) -> str:
    return "" if value is None else str(value).strip()


def _person_tokens(value) -> set[str]:
    """兼容“张三/已离职”和多人责任字段，同时仍以完整姓名精确匹配。"""
    return {
        token.strip()
        for token in PERSON_SEPARATOR.split(_clean(value))
        if token.strip() not in IGNORED_PERSON_MARKERS
    }


def responsibility_matches(adm_owner: str, finance_person: str) -> bool:
    owner = _clean(adm_owner)
    return bool(owner and owner in _person_tokens(finance_person))


def apply_finance_diff_status(
    rows: list[dict],
    records_by_adm_no: dict[str, list[dict]],
) -> None:
    """按ADM单号匹配财务表ota_order_no，并写入处理进度核验结果。"""
    for row in rows:
        adm_no = _clean(row.get("adm_no"))
        matches = records_by_adm_no.get(adm_no, []) if adm_no else []
        primary_owner = _clean(row.get("actual_owner")) or _clean(row.get("owner"))
        creators = sorted({
            _clean(item.get("create_user_name"))
            for item in matches
            if _clean(item.get("create_user_name"))
        })
        duty_people = sorted({
            _clean(item.get("duty_person"))
            for item in matches
            if _clean(item.get("duty_person"))
        })
        owner_match = any(
            responsibility_matches(primary_owner, item.get("create_user_name"))
            for item in matches
        )

        if not matches:
            progress = "无差异单"
        elif owner_match:
            progress = "已录入差异"
        else:
            progress = "有差异单不是责任人录入"

        row.update({
            "finance_diff_checked": True,
            "finance_diff_count": len(matches),
            "finance_diff_creators": creators,
            "finance_diff_duty_persons": duty_people,
            "finance_diff_owner_match": owner_match,
            "finance_handling_progress": progress,
        })


class FinanceDiffLookup:
    """只读查询财务差异表；不对财务库执行任何写操作。"""

    def __init__(self, engine: Engine, chunk_size: int = 1000):
        self.engine = engine
        self.chunk_size = chunk_size

    def health(self) -> str:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return "UP"

    def attach(self, rows: list[dict]) -> None:
        adm_numbers = list(dict.fromkeys(
            _clean(row.get("adm_no")) for row in rows if _clean(row.get("adm_no"))
        ))
        records: dict[str, list[dict]] = defaultdict(list)
        query = text(
            """
            SELECT ota_order_no, create_user_name, duty_person
            FROM order_info_diff_reason
            WHERE status = 1
              AND ota_order_no IN :adm_numbers
            """
        ).bindparams(bindparam("adm_numbers", expanding=True))

        try:
            with self.engine.connect() as connection:
                for start in range(0, len(adm_numbers), self.chunk_size):
                    chunk = adm_numbers[start:start + self.chunk_size]
                    for result in connection.execute(query, {"adm_numbers": chunk}):
                        item = dict(result._mapping)
                        records[_clean(item.get("ota_order_no"))].append(item)
        except SQLAlchemyError as error:
            raise AppError(
                "财务差异库查询失败，已停止生成处理进度，避免把未核验数据误报为无差异单",
                503,
            ) from error

        apply_finance_diff_status(rows, records)
