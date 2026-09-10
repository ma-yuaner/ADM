from __future__ import annotations

import html
import re
import sys
from abc import ABC, abstractmethod
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import Engine

from .domain import alert_info, serialize_task, stage_code
from .errors import AppError
from .finance_diff import FinanceDiffLookup, apply_finance_diff_status


TASK_COLUMNS = """
    id, adm_no, ota_code, ota_order_no, supplier_code, airline,
    ticket_no, ticket_count, total_amount, currency, supply_issue_date,
    adm_deadline, owner, actual_owner, lock_flag, adm_status,
    appeal_status, appeal_result, diff_detail_reason, appeal_reason,
    resolution, create_time, update_time
"""

IMPORT_SOURCE_COLUMNS = """
    id, adm_no, ota_code, ota_order_no, lock_flag, lock_operator_id,
    lock_operator, supplier_code, airline, supplier_type, ticket_no,
    ticket_count, total_amount, currency, supply_issue_date, adm_deadline,
    category, diff_type, diff_detail_reason, owner, actual_owner,
    adm_status, appeal_status, appeal_result, appeal_reason, resolution,
    handle_time, auditor_name, auditor_time, auditor_remark, actual_handler,
    file_url, status, remark, create_time, update_time, create_user_name,
    update_user_name
"""

FIELD_CHANGE_PATTERN = re.compile(
    r"<b>(?P<field>.*?)</b>\s*由\s*'(?P<old>.*?)'\s*修改为\s*'(?P<new>.*?)'",
    flags=re.IGNORECASE | re.DOTALL,
)
TAG_PATTERN = re.compile(r"<[^>]+>")


def _field_changes(value) -> list[tuple[str, str, str]]:
    raw = html.unescape(str(value or ""))
    changes = []
    for match in FIELD_CHANGE_PATTERN.finditer(raw):
        changes.append(tuple(
            TAG_PATTERN.sub("", match.group(name)).strip()
            for name in ("field", "old", "new")
        ))
    return changes


def attach_transfer_history(rows: list[dict], logs: list[dict]) -> None:
    """把操作日志中的实际责任人变化和转单后首次锁单信息写回ADM行。"""
    events: dict[int, dict] = {}
    for log in logs:
        adm_id = int(log["business_obj_id"])
        event = events.setdefault(adm_id, {"transfers": [], "locks": []})
        event_time = log.get("operator_datetime")
        if not isinstance(event_time, datetime):
            continue
        for field, old_value, new_value in _field_changes(log.get("operator_content")):
            if field == "实际责任人" and old_value != new_value and new_value:
                event["transfers"].append({
                    "time": event_time,
                    "from": old_value,
                    "to": new_value,
                    "operator": str(log.get("operator_name") or "").strip(),
                })
            elif field == "锁状态" and new_value == "已锁定":
                event["locks"].append(event_time)

    for row in rows:
        history = events.get(int(row["id"]), {"transfers": [], "locks": []})
        transfers = sorted(history["transfers"], key=lambda item: item["time"])
        last_transfer = transfers[-1] if transfers else None
        post_transfer_lock = None
        if last_transfer:
            post_transfer_lock = next(
                (value for value in sorted(history["locks"]) if value > last_transfer["time"]),
                None,
            )
        row.update({
            "transfer_count": len(transfers),
            "last_transfer_time": last_transfer["time"] if last_transfer else None,
            "last_transfer_from": last_transfer["from"] if last_transfer else "",
            "last_transfer_to": last_transfer["to"] if last_transfer else "",
            "last_transfer_operator": last_transfer["operator"] if last_transfer else "",
            "post_transfer_lock_time": post_transfer_lock,
            "transfer_awaiting_acceptance": bool(last_transfer and not post_transfer_lock),
        })


class AdmRepository(ABC):
    mode = "unknown"

    @abstractmethod
    def health(self) -> dict:
        raise NotImplementedError

    @abstractmethod
    def people(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def list_tasks(self, filters: dict) -> dict:
        raise NotImplementedError

    @abstractmethod
    def assign(self, adm_ids: list[int], actual_owner: str, actor: str, client_ip: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    def find_by_adm_numbers(self, adm_numbers: list[str]) -> dict[str, dict]:
        raise NotImplementedError

    @abstractmethod
    def find_import_rows_by_adm_numbers(self, adm_numbers: list[str]) -> dict[str, dict]:
        raise NotImplementedError


class MySQLAdmRepository(AdmRepository):
    mode = "mysql"

    def __init__(
        self,
        engine: Engine,
        write_enabled: bool,
        operator_id: int = 0,
        finance_diff_lookup: FinanceDiffLookup | None = None,
    ):
        self.engine = engine
        self.write_enabled = write_enabled
        self.operator_id = operator_id
        self.finance_diff_lookup = finance_diff_lookup

    def health(self) -> dict:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        finance_database = (
            self.finance_diff_lookup.health() if self.finance_diff_lookup else "DISABLED"
        )
        return {
            "database": "UP",
            "financeDatabase": finance_database,
            "writeEnabled": self.write_enabled,
        }

    def people(self) -> list[str]:
        sql = text(
            """
            SELECT person
            FROM (
                SELECT TRIM(owner) AS person
                FROM adm_records
                WHERE status = 1 AND owner IS NOT NULL AND TRIM(owner) <> ''
                UNION
                SELECT TRIM(actual_owner) AS person
                FROM adm_records
                WHERE status = 1 AND actual_owner IS NOT NULL AND TRIM(actual_owner) <> ''
            ) people
            ORDER BY person
            """
        )
        with self.engine.connect() as connection:
            return [row.person for row in connection.execute(sql)]

    @staticmethod
    def _scope_sql(scope: str, person: str, params: dict) -> str:
        if scope == "mine":
            if not person:
                raise AppError("查看我的待办时必须选择人员")
            params["person"] = person
            return "AND (TRIM(COALESCE(actual_owner, '')) = :person OR (TRIM(COALESCE(actual_owner, '')) = '' AND TRIM(COALESCE(owner, '')) = :person))"
        if scope == "team":
            if not person:
                raise AppError("查看团队待办时必须选择负责人")
            params["person"] = person
            return "AND TRIM(COALESCE(owner, '')) = :person"
        if scope == "all":
            return ""
        raise AppError("scope仅支持mine、team或all")

    def list_tasks(self, filters: dict) -> dict:
        params: dict = {}
        where = ["status = 1", "COALESCE(adm_status, -1) <> 3"]
        scope_clause = self._scope_sql(filters["scope"], filters["person"], params)
        if scope_clause:
            where.append(scope_clause.removeprefix("AND "))
        if filters.get("source"):
            params["source"] = filters["source"]
            where.append("COALESCE(NULLIF(TRIM(ota_code), ''), '未配置') = :source")
        if filters.get("search"):
            params["search"] = f"%{filters['search']}%"
            where.append("(adm_no LIKE :search OR ota_order_no LIKE :search OR ticket_no LIKE :search)")

        where_sql = " AND ".join(f"({item})" for item in where)
        sql = text(f"SELECT {TASK_COLUMNS} FROM adm_records WHERE {where_sql} ORDER BY adm_deadline IS NULL, adm_deadline, id DESC")
        with self.engine.connect() as connection:
            rows = [dict(row._mapping) for row in connection.execute(sql, params)]
            if rows:
                log_sql = text(
                    """
                    SELECT id, business_obj_id, operator_datetime,
                           operator_name, operator_content
                    FROM auto_issue_operator_log
                    WHERE business_obj = 'AdmRecords'
                      AND business_obj_id IN :adm_ids
                      AND (operator_content LIKE '%实际责任人%'
                           OR operator_content LIKE '%锁状态%')
                    ORDER BY business_obj_id, operator_datetime, id
                    """
                ).bindparams(bindparam("adm_ids", expanding=True))
                logs = [
                    dict(log._mapping)
                    for log in connection.execute(log_sql, {"adm_ids": [row["id"] for row in rows]})
                ]
                attach_transfer_history(rows, logs)

        if self.finance_diff_lookup:
            self.finance_diff_lookup.attach(rows)

        tasks = [serialize_task(row) for row in rows]
        if filters.get("alert"):
            tasks = [item for item in tasks if item["alertLevel"] == filters["alert"]]
        if filters.get("stage"):
            tasks = [item for item in tasks if item["stageCode"] == filters["stage"]]

        total = len(tasks)
        page = filters["page"]
        page_size = filters["page_size"]
        start = (page - 1) * page_size
        paged = tasks[start:start + page_size]
        summary = {
            "currentOpen": total,
            "unassigned": sum(not item["actualOwner"] for item in tasks),
            "assigned": sum(bool(item["actualOwner"]) for item in tasks),
            "overdue": sum(item["alertLevel"] == "P0" and item["alertText"] == "超过截止时间" for item in tasks),
            "due24h": sum(item["alertLevel"] == "P1" and item["alertText"] == "24小时内到期" for item in tasks),
        }
        sources = sorted({item["otaCode"] for item in tasks})
        return {
            "items": paged,
            "summary": summary,
            "sources": sources,
            "pagination": {"page": page, "pageSize": page_size, "total": total},
            "updatedAt": datetime.now(),
        }

    def assign(self, adm_ids: list[int], actual_owner: str, actor: str, client_ip: str) -> dict:
        if not self.write_enabled:
            raise AppError("当前环境未开启数据库写入，请设置ADM_WRITE_ENABLED=true", 403)
        if not adm_ids:
            raise AppError("至少选择一张ADM")
        placeholders = ", ".join(f":id_{index}" for index in range(len(adm_ids)))
        params = {f"id_{index}": value for index, value in enumerate(adm_ids)}
        select_sql = text(
            f"SELECT id, adm_no, actual_owner, status, adm_status FROM adm_records "
            f"WHERE id IN ({placeholders}) FOR UPDATE"
        )
        now = datetime.now()
        updated: list[int] = []
        skipped: list[dict] = []

        with self.engine.begin() as connection:
            rows = [dict(row._mapping) for row in connection.execute(select_sql, params)]
            found = {int(row["id"]) for row in rows}
            for missing in sorted(set(adm_ids) - found):
                skipped.append({"id": missing, "reason": "ADM不存在"})

            for row in rows:
                adm_id = int(row["id"])
                if row.get("status") != 1:
                    skipped.append({"id": adm_id, "reason": "ADM已失效或暂停"})
                    continue
                if row.get("adm_status") == 3:
                    skipped.append({"id": adm_id, "reason": "ADM已结案"})
                    continue
                old_owner = str(row.get("actual_owner") or "").strip()
                if old_owner == actual_owner:
                    skipped.append({"id": adm_id, "reason": "实际处理人未变化"})
                    continue

                connection.execute(
                    text(
                        "UPDATE adm_records SET actual_owner=:actual_owner, "
                        "update_user_name=:actor, update_time=:now WHERE id=:adm_id"
                    ),
                    {"actual_owner": actual_owner, "actor": actor, "now": now, "adm_id": adm_id},
                )
                version = connection.execute(
                    text(
                        "SELECT COALESCE(MAX(version), 0) + 1 FROM auto_issue_operator_log "
                        "WHERE business_obj='AdmRecords' AND business_obj_id=:adm_id"
                    ),
                    {"adm_id": adm_id},
                ).scalar_one()
                content = (
                    "【修改信息】<br>"
                    f"【<b>实际责任人</b> 由 '{html.escape(old_owner)}' 修改为 '{html.escape(actual_owner)}'】"
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO auto_issue_operator_log (
                            business_obj, business_obj_id, operator_type,
                            operator_datetime, operator_by, operator_name,
                            operator_content, login_ip, manual_flag, version,
                            create_time, update_time, create_user_id,
                            create_user_name, update_user_id, update_user_name
                        ) VALUES (
                            'AdmRecords', :adm_id, '修改', :now, :operator_id,
                            :actor, :content, :client_ip, 1, :version, :now,
                            :now, :operator_id, :actor, :operator_id, :actor
                        )
                        """
                    ),
                    {
                        "adm_id": adm_id,
                        "now": now,
                        "operator_id": self.operator_id,
                        "actor": actor[:20],
                        "content": content,
                        "client_ip": client_ip[:30],
                        "version": int(version),
                    },
                )
                updated.append(adm_id)

        return {"updatedIds": updated, "updatedCount": len(updated), "skipped": skipped}

    def find_by_adm_numbers(self, adm_numbers: list[str]) -> dict[str, dict]:
        normalized = list(dict.fromkeys(value.strip() for value in adm_numbers if value.strip()))
        if not normalized:
            return {}
        sql = text(
            f"SELECT {TASK_COLUMNS} FROM adm_records "
            "WHERE status = 1 AND adm_no IN :adm_numbers"
        ).bindparams(bindparam("adm_numbers", expanding=True))
        with self.engine.connect() as connection:
            rows = [
                dict(row._mapping)
                for row in connection.execute(sql, {"adm_numbers": normalized})
            ]
        return {task["admNo"]: task for task in (serialize_task(row) for row in rows)}

    def find_import_rows_by_adm_numbers(self, adm_numbers: list[str]) -> dict[str, dict]:
        normalized = list(dict.fromkeys(value.strip() for value in adm_numbers if value.strip()))
        if not normalized:
            return {}

        rows: list[dict] = []
        with self.engine.connect() as connection:
            for start in range(0, len(normalized), 1000):
                batch = normalized[start:start + 1000]
                sql = text(
                    f"SELECT {IMPORT_SOURCE_COLUMNS} FROM adm_records "
                    "WHERE status = 1 AND adm_no IN :adm_numbers"
                ).bindparams(bindparam("adm_numbers", expanding=True))
                rows.extend(
                    dict(row._mapping)
                    for row in connection.execute(sql, {"adm_numbers": batch})
                )
        return {str(row["adm_no"]).strip(): row for row in rows}


class MockAdmRepository(AdmRepository):
    mode = "mock"

    def __init__(self):
        now = datetime.now().replace(microsecond=0)
        self.rows = [
            self._row(101, "ADM-260909-001", "CTRIP", "26090981021", "MU", 4860, "CNY", "黄娜娟", "", 0, 0, now - timedelta(hours=20), now - timedelta(days=1)),
            self._row(102, "ADM-260909-002", "QUNAR", "26090981036", "SQ", 520, "USD", "黄娜娟", "马远尔", 1, 0, now + timedelta(hours=12), now - timedelta(hours=5)),
            self._row(103, "ADM-260909-003", "FLIGGY", "26090766219", "CZ", 2310, "CNY", "黄娜娟", "李志君", 1, 1, now + timedelta(days=2), now - timedelta(days=8)),
            self._row(104, "ADM-260909-004", "LY", "26090651993", "EK", 185, "USD", "黄娜娟", "", 1, 0, now + timedelta(days=3), now - timedelta(days=4)),
            self._row(105, "ADM-260909-005", "CTRIP", "26090981107", "CA", 980, "CNY", "黄娜娟", "马远尔", 0, 0, now + timedelta(days=6), now - timedelta(hours=2)),
            self._row(106, "ADM-260909-006", "QUNAR", "26090548277", "CX", 2760, "HKD", "黄娜娟", "李志君", 1, None, now + timedelta(hours=18), now - timedelta(hours=1)),
            self._row(107, "ADM-260909-007", "CTRIP", "26090981120", "ZH", 1320, "CNY", "李志君", "", 0, 0, now + timedelta(days=4), now - timedelta(hours=3)),
        ]
        self.finance_records = {
            "ADM-260909-001": [{"create_user_name": "黄娜娟", "duty_person": ""}],
            "ADM-260909-002": [{"create_user_name": "黄娜娟", "duty_person": ""}],
        }

    @staticmethod
    def _row(id_, adm_no, source, order, airline, amount, currency, owner, actual_owner, lock_flag, adm_status, deadline, updated):
        return {
            "id": id_, "adm_no": adm_no, "ota_code": source, "ota_order_no": order,
            "supplier_code": "", "airline": airline, "ticket_no": f"781-50000{id_}",
            "ticket_count": 1, "total_amount": amount, "currency": currency,
            "supply_issue_date": updated.date(), "adm_deadline": deadline, "owner": owner,
            "actual_owner": actual_owner, "lock_flag": lock_flag, "adm_status": adm_status,
            "appeal_status": None, "appeal_result": None, "create_time": updated,
            "diff_detail_reason": "航司收回前期返点" if id_ % 2 else "",
            "appeal_reason": "已提交航司政策及出票记录" if adm_status == 1 else "",
            "resolution": "", "update_time": updated, "status": 1,
            "lock_operator_id": None, "lock_operator": "",
            "supplier_type": 3, "category": 0, "diff_type": 4,
            "handle_time": None, "auditor_name": "", "auditor_time": None,
            "auditor_remark": "", "actual_handler": "", "file_url": "",
            "remark": "原系统备注", "create_user_name": "曾芸芸",
            "update_user_name": "曾芸芸",
            "transfer_count": 0, "last_transfer_time": None,
            "last_transfer_from": "", "last_transfer_to": "",
            "last_transfer_operator": "", "post_transfer_lock_time": None,
            "transfer_awaiting_acceptance": False,
        }

    def health(self) -> dict:
        return {"database": "MOCK", "financeDatabase": "MOCK", "writeEnabled": True}

    def people(self) -> list[str]:
        values = {"曾芸芸", "黄娜娟", "李志君", "马远尔"}
        for row in self.rows:
            values.update(filter(None, [row.get("owner"), row.get("actual_owner")]))
        return sorted(values)

    def list_tasks(self, filters: dict) -> dict:
        rows = deepcopy(self.rows)
        person = filters["person"]
        scope = filters["scope"]
        if scope == "mine":
            rows = [row for row in rows if row.get("actual_owner") == person or (not row.get("actual_owner") and row.get("owner") == person)]
        elif scope == "team":
            rows = [row for row in rows if row.get("owner") == person]
        elif scope != "all":
            raise AppError("scope仅支持mine、team或all")
        if filters.get("source"):
            rows = [row for row in rows if (row.get("ota_code") or "未配置") == filters["source"]]
        query = filters.get("search", "").lower()
        if query:
            rows = [row for row in rows if query in row["adm_no"].lower() or query in row["ota_order_no"].lower() or query in row["ticket_no"].lower()]

        apply_finance_diff_status(rows, self.finance_records)
        tasks = [serialize_task(row) for row in rows if row.get("status") == 1 and row.get("adm_status") != 3]
        if filters.get("alert"):
            tasks = [item for item in tasks if item["alertLevel"] == filters["alert"]]
        if filters.get("stage"):
            tasks = [item for item in tasks if item["stageCode"] == filters["stage"]]
        tasks.sort(key=lambda item: (item["deadline"] is None, item["deadline"] or datetime.max, -item["id"]))
        total = len(tasks)
        page, page_size = filters["page"], filters["page_size"]
        start = (page - 1) * page_size
        return {
            "items": tasks[start:start + page_size],
            "summary": {
                "currentOpen": total,
                "unassigned": sum(not item["actualOwner"] for item in tasks),
                "assigned": sum(bool(item["actualOwner"]) for item in tasks),
                "overdue": sum(item["alertText"] == "超过截止时间" for item in tasks),
                "due24h": sum(item["alertText"] == "24小时内到期" for item in tasks),
            },
            "sources": sorted({item["otaCode"] for item in tasks}),
            "pagination": {"page": page, "pageSize": page_size, "total": total},
            "updatedAt": datetime.now(),
        }

    def assign(self, adm_ids: list[int], actual_owner: str, actor: str, client_ip: str) -> dict:
        updated, skipped = [], []
        indexed = {row["id"]: row for row in self.rows}
        for adm_id in adm_ids:
            row = indexed.get(adm_id)
            if not row:
                skipped.append({"id": adm_id, "reason": "ADM不存在"})
            elif row.get("adm_status") == 3:
                skipped.append({"id": adm_id, "reason": "ADM已结案"})
            elif row.get("actual_owner") == actual_owner:
                skipped.append({"id": adm_id, "reason": "实际处理人未变化"})
            else:
                old_owner = row.get("actual_owner") or ""
                now = datetime.now().replace(microsecond=0)
                row["actual_owner"] = actual_owner
                row["update_time"] = now
                row["transfer_count"] = int(row.get("transfer_count") or 0) + 1
                row["last_transfer_time"] = now
                row["last_transfer_from"] = old_owner
                row["last_transfer_to"] = actual_owner
                row["last_transfer_operator"] = actor
                row["post_transfer_lock_time"] = None
                row["transfer_awaiting_acceptance"] = True
                updated.append(adm_id)
        return {"updatedIds": updated, "updatedCount": len(updated), "skipped": skipped}

    def find_by_adm_numbers(self, adm_numbers: list[str]) -> dict[str, dict]:
        wanted = {value.strip() for value in adm_numbers if value.strip()}
        return {
            task["admNo"]: task
            for task in (serialize_task(deepcopy(row)) for row in self.rows)
            if task["admNo"] in wanted
        }

    def find_import_rows_by_adm_numbers(self, adm_numbers: list[str]) -> dict[str, dict]:
        wanted = {value.strip() for value in adm_numbers if value.strip()}
        return {
            str(row["adm_no"]).strip(): deepcopy(row)
            for row in self.rows
            if str(row.get("adm_no") or "").strip() in wanted and row.get("status") == 1
        }


def _repo_engine(project_dir: Path) -> Engine:
    repo_root = project_dir.parent
    analysis_scripts = repo_root / "analysis" / "scripts"
    for path in (repo_root, analysis_scripts):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    from common_libs.config.db_config import erp_config

    return erp_config.get_connect()


def _repo_finance_engine(project_dir: Path) -> Engine:
    repo_root = project_dir.parent
    analysis_scripts = repo_root / "analysis" / "scripts"
    for path in (repo_root, analysis_scripts):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    from common_libs.config.db_config import fi_config

    return fi_config.get_connect()


def _mysql_engine(config: dict, prefix: str) -> Engine:
    return create_engine(
        "mysql+pymysql://",
        creator=lambda: __import__("pymysql").connect(
            host=config[f"{prefix}_HOST"],
            port=config[f"{prefix}_PORT"],
            user=config[f"{prefix}_USER"],
            password=config[f"{prefix}_PASSWORD"],
            database=config[f"{prefix}_DATABASE"],
            charset="utf8mb4",
            connect_timeout=15,
            read_timeout=60,
            write_timeout=60,
        ),
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=5,
        max_overflow=5,
    )


def create_repository(config: dict, project_dir: Path) -> AdmRepository:
    mode = config["DATA_MODE"]
    if mode == "mock":
        return MockAdmRepository()
    if mode == "repo":
        finance_lookup = (
            FinanceDiffLookup(_repo_finance_engine(project_dir))
            if config["FINANCE_DIFF_ENABLED"]
            else None
        )
        return MySQLAdmRepository(
            _repo_engine(project_dir),
            config["WRITE_ENABLED"],
            config["OPERATOR_ID"],
            finance_lookup,
        )
    if mode == "mysql":
        missing = [name for name in ("DB_HOST", "DB_USER", "DB_PASSWORD", "DB_DATABASE") if not config.get(name)]
        if missing:
            raise RuntimeError(f"mysql模式缺少配置：{', '.join(missing)}")
        finance_lookup = None
        if config["FINANCE_DIFF_ENABLED"]:
            finance_missing = [
                name
                for name in (
                    "FINANCE_DB_HOST", "FINANCE_DB_USER", "FINANCE_DB_PASSWORD",
                    "FINANCE_DB_DATABASE",
                )
                if not config.get(name)
            ]
            if finance_missing:
                raise RuntimeError(
                    f"启用财务差异核验后缺少配置：{', '.join(finance_missing)}"
                )
            finance_lookup = FinanceDiffLookup(_mysql_engine(config, "FINANCE_DB"))
        return MySQLAdmRepository(
            _mysql_engine(config, "DB"),
            config["WRITE_ENABLED"],
            config["OPERATOR_ID"],
            finance_lookup,
        )
    raise RuntimeError("ADM_DATA_MODE仅支持mock、repo或mysql")
