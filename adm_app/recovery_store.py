from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from .errors import AppError


STATUS_NAMES = {
    "PENDING": "待恢复",
    "PROCESSING": "恢复中",
    "COMPLETED": "已完成",
    "EXCEPTION": "异常",
}


class RecoveryStore:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=20)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS adm_recovery_followup (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    adm_record_id INTEGER NOT NULL,
                    adm_no TEXT NOT NULL UNIQUE,
                    ota_code TEXT NOT NULL DEFAULT '',
                    ota_order_no TEXT NOT NULL DEFAULT '',
                    ticket_no TEXT NOT NULL DEFAULT '',
                    airline TEXT NOT NULL DEFAULT '',
                    owner TEXT NOT NULL DEFAULT '',
                    actual_owner TEXT NOT NULL DEFAULT '',
                    recovery_code TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    remark TEXT NOT NULL DEFAULT '',
                    imported_by TEXT NOT NULL DEFAULT '',
                    import_time TEXT NOT NULL,
                    handled_by TEXT NOT NULL DEFAULT '',
                    handled_at TEXT,
                    update_time TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_recovery_status
                    ON adm_recovery_followup(status, update_time);
                CREATE INDEX IF NOT EXISTS idx_recovery_code
                    ON adm_recovery_followup(recovery_code);
                """
            )

    def upsert(self, task: dict, recovery_code: str, imported_by: str) -> str:
        now = datetime.now().replace(microsecond=0).isoformat(sep=" ")
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT recovery_code, status FROM adm_recovery_followup WHERE adm_no = ?",
                (task["admNo"],),
            ).fetchone()
            changed = existing is not None and existing["recovery_code"] != recovery_code
            status = "PENDING" if existing is None or changed else existing["status"]
            connection.execute(
                """
                INSERT INTO adm_recovery_followup (
                    adm_record_id, adm_no, ota_code, ota_order_no, ticket_no,
                    airline, owner, actual_owner, recovery_code, status,
                    imported_by, import_time, update_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(adm_no) DO UPDATE SET
                    adm_record_id = excluded.adm_record_id,
                    ota_code = excluded.ota_code,
                    ota_order_no = excluded.ota_order_no,
                    ticket_no = excluded.ticket_no,
                    airline = excluded.airline,
                    owner = excluded.owner,
                    actual_owner = excluded.actual_owner,
                    recovery_code = excluded.recovery_code,
                    status = excluded.status,
                    imported_by = excluded.imported_by,
                    import_time = excluded.import_time,
                    remark = CASE WHEN excluded.status = 'PENDING' THEN '' ELSE remark END,
                    handled_by = CASE WHEN excluded.status = 'PENDING' THEN '' ELSE handled_by END,
                    handled_at = CASE WHEN excluded.status = 'PENDING' THEN NULL ELSE handled_at END,
                    update_time = excluded.update_time
                """,
                (
                    task["id"], task["admNo"], task["otaCode"], task["otaOrderNo"],
                    task["ticketNo"], task["airline"], task["owner"],
                    task["actualOwner"], recovery_code, status, imported_by, now, now,
                ),
            )
        if existing is None:
            return "created"
        return "reset" if changed else "unchanged"

    @staticmethod
    def _serialize(row: sqlite3.Row) -> dict:
        item = dict(row)
        item["statusName"] = STATUS_NAMES.get(item["status"], item["status"])
        return item

    def list(self, status: str, search: str, page: int, page_size: int) -> dict:
        where = ["1 = 1"]
        params: list[object] = []
        if status:
            if status not in STATUS_NAMES:
                raise AppError("恢复状态不正确")
            where.append("status = ?")
            params.append(status)
        if search:
            where.append(
                "(adm_no LIKE ? OR ota_order_no LIKE ? OR ticket_no LIKE ? OR recovery_code LIKE ?)"
            )
            value = f"%{search}%"
            params.extend([value, value, value, value])
        where_sql = " AND ".join(where)
        with self._connect() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM adm_recovery_followup WHERE {where_sql}", params
            ).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT * FROM adm_recovery_followup
                WHERE {where_sql}
                ORDER BY
                    CASE status
                        WHEN 'PENDING' THEN 1 WHEN 'EXCEPTION' THEN 2
                        WHEN 'PROCESSING' THEN 3 ELSE 4
                    END,
                    update_time DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                [*params, page_size, (page - 1) * page_size],
            ).fetchall()
            summary_rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM adm_recovery_followup GROUP BY status"
            ).fetchall()
        summary = {key: 0 for key in STATUS_NAMES}
        summary.update({row["status"]: row["count"] for row in summary_rows})
        return {
            "items": [self._serialize(row) for row in rows],
            "summary": summary,
            "pagination": {"page": page, "pageSize": page_size, "total": total},
        }

    def find_by_adm_numbers(self, adm_numbers: list[str]) -> dict[str, dict]:
        """按ADM单号批量返回当前恢复编码跟进记录。"""
        unique_numbers = list(dict.fromkeys(number for number in adm_numbers if number))
        if not unique_numbers:
            return {}

        result: dict[str, dict] = {}
        with self._connect() as connection:
            # SQLite默认变量数量有限，分批查询避免大文件转换时报错。
            for start in range(0, len(unique_numbers), 500):
                batch = unique_numbers[start:start + 500]
                placeholders = ",".join("?" for _ in batch)
                rows = connection.execute(
                    f"SELECT * FROM adm_recovery_followup WHERE adm_no IN ({placeholders})",
                    batch,
                ).fetchall()
                result.update({row["adm_no"]: self._serialize(row) for row in rows})
        return result

    def update(self, item_id: int, status: str, remark: str, handler: str) -> dict:
        if status not in STATUS_NAMES:
            raise AppError("恢复状态不正确")
        now = datetime.now().replace(microsecond=0).isoformat(sep=" ")
        handled_at = now if status in {"COMPLETED", "EXCEPTION"} else None
        with self._connect() as connection:
            result = connection.execute(
                """
                UPDATE adm_recovery_followup
                SET status = ?, remark = ?, handled_by = ?, handled_at = ?, update_time = ?
                WHERE id = ?
                """,
                (status, remark, handler, handled_at, now, item_id),
            )
            if result.rowcount == 0:
                raise AppError("恢复编码记录不存在", 404)
            row = connection.execute(
                "SELECT * FROM adm_recovery_followup WHERE id = ?", (item_id,)
            ).fetchone()
        return self._serialize(row)

    def update_code(self, item_id: int, recovery_code: str, handler: str) -> dict:
        now = datetime.now().replace(microsecond=0).isoformat(sep=" ")
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT recovery_code FROM adm_recovery_followup WHERE id = ?", (item_id,)
            ).fetchone()
            if existing is None:
                raise AppError("恢复编码记录不存在", 404)
            changed = existing["recovery_code"] != recovery_code
            if changed:
                connection.execute(
                    """
                    UPDATE adm_recovery_followup
                    SET recovery_code = ?, status = 'PENDING', remark = '',
                        handled_by = ?, handled_at = NULL, update_time = ?
                    WHERE id = ?
                    """,
                    (recovery_code, handler, now, item_id),
                )
            row = connection.execute(
                "SELECT * FROM adm_recovery_followup WHERE id = ?", (item_id,)
            ).fetchone()
        item = self._serialize(row)
        item["codeChanged"] = changed
        return item

    def delete(self, item_id: int) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM adm_recovery_followup WHERE id = ?", (item_id,)
            ).fetchone()
            if row is None:
                raise AppError("恢复编码记录不存在", 404)
            connection.execute("DELETE FROM adm_recovery_followup WHERE id = ?", (item_id,))
        return self._serialize(row)
