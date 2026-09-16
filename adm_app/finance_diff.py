from __future__ import annotations

from collections import defaultdict

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from .errors import AppError


def _clean(value) -> str:
    return "" if value is None else str(value).strip()


def apply_finance_diff_status(
    rows: list[dict],
    records_by_adm_no: dict[str, list[dict]],
) -> None:
    """按ADM业务单号匹配有效支出差异单，不进行订单或人员匹配。"""
    for row in rows:
        adm_no = _clean(row.get("adm_no"))
        matches = [
            item for item in records_by_adm_no.get(adm_no, [])
            if _clean(item.get("business_ref_no")) == adm_no
            and (item.get("calculate_rate") == -1 or _clean(item.get("calculate_rate")) in {"-1", "-1.0"})
            and ("status" not in item or _clean(item["status"]) == "1")
        ] if adm_no else []
        duty_people = sorted({
            _clean(item.get("duty_person"))
            for item in matches
            if _clean(item.get("duty_person"))
        })
        progress = "已录入差异" if matches else "无差异单"

        row.update({
            "finance_diff_checked": True,
            "finance_diff_count": len(matches),
            "finance_diff_duty_persons": duty_people,
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
            SELECT business_ref_no, duty_person, calculate_rate
            FROM order_info_diff_reason
            WHERE status = 1
              AND calculate_rate = -1
              AND business_ref_no IN :adm_numbers
            """
        ).bindparams(bindparam("adm_numbers", expanding=True))

        try:
            with self.engine.connect() as connection:
                for start in range(0, len(adm_numbers), self.chunk_size):
                    chunk = adm_numbers[start:start + self.chunk_size]
                    for result in connection.execute(query, {"adm_numbers": chunk}):
                        item = dict(result._mapping)
                        records[_clean(item.get("business_ref_no"))].append(item)
        except SQLAlchemyError as error:
            raise AppError(
                "财务差异库查询失败，已停止生成处理进度，避免把未核验数据误报为无差异单",
                503,
            ) from error

        apply_finance_diff_status(rows, records)
