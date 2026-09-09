from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal


STAGE_NAMES = {
    "UNASSIGNED": "待分配",
    "ASSIGNED_UNLOCKED": "已分配未接单",
    "LOCKED_PENDING_DECISION": "已锁单待决策",
    "APPEALING": "申诉中",
    "NO_APPEAL_PENDING_AUDIT": "不申诉待审核",
    "APPEAL_SUCCESS_PENDING_AUDIT": "申诉成功待审核",
    "APPEAL_FAIL_PENDING_AUDIT": "申诉失败待审核",
    "PENDING_AUDIT_OTHER": "其他待审核",
    "STATUS_ABNORMAL": "状态异常",
    "CLOSED": "已结案",
}


def text_value(value) -> str:
    return "" if value is None else str(value).strip()


def stage_code(row: dict) -> str:
    adm_status = row.get("adm_status")
    appeal_status = row.get("appeal_status")
    appeal_result = row.get("appeal_result")
    owner = text_value(row.get("owner"))
    lock_flag = int(row.get("lock_flag") or 0)

    if adm_status == 3:
        return "CLOSED"
    if adm_status not in {0, 1, 2}:
        return "STATUS_ABNORMAL"
    if not owner:
        return "UNASSIGNED"
    if adm_status == 0:
        return "LOCKED_PENDING_DECISION" if lock_flag else "ASSIGNED_UNLOCKED"
    if adm_status == 1:
        return "APPEALING"
    if appeal_status == 1:
        return "NO_APPEAL_PENDING_AUDIT"
    if appeal_status == 0 and appeal_result == 0:
        return "APPEAL_SUCCESS_PENDING_AUDIT"
    if appeal_status == 0 and appeal_result == 1:
        return "APPEAL_FAIL_PENDING_AUDIT"
    return "PENDING_AUDIT_OTHER"


def alert_info(row: dict, now: datetime | None = None) -> tuple[str, str]:
    now = now or datetime.now()
    code = stage_code(row)
    deadline = row.get("adm_deadline")
    updated = row.get("update_time") or row.get("create_time")

    if code == "STATUS_ABNORMAL":
        return "P0", "状态异常"
    if isinstance(deadline, datetime) and deadline < now:
        return "P0", "超过截止时间"
    if isinstance(deadline, datetime) and deadline <= now + timedelta(hours=24):
        return "P1", "24小时内到期"
    if code == "APPEALING" and isinstance(updated, datetime) and updated < now - timedelta(days=7):
        return "P1", "申诉超过7天"
    if isinstance(updated, datetime) and updated < now - timedelta(days=3):
        return "P2", "超过3天无更新"
    return "NORMAL", "正常"


def serialize_task(row: dict, now: datetime | None = None) -> dict:
    code = stage_code(row)
    alert_level, alert_text = alert_info(row, now)
    amount = row.get("total_amount")
    if isinstance(amount, Decimal):
        amount = float(amount)
    return {
        "id": int(row["id"]),
        "admNo": text_value(row.get("adm_no")),
        "otaCode": text_value(row.get("ota_code")) or "未配置",
        "otaOrderNo": text_value(row.get("ota_order_no")),
        "supplierCode": text_value(row.get("supplier_code")),
        "airline": text_value(row.get("airline")) or "未配置",
        "ticketNo": text_value(row.get("ticket_no")),
        "ticketCount": int(row.get("ticket_count") or 0),
        "amount": amount or 0,
        "currency": text_value(row.get("currency")) or "CNY",
        "supplyIssueDate": row.get("supply_issue_date"),
        "deadline": row.get("adm_deadline"),
        "owner": text_value(row.get("owner")),
        "actualOwner": text_value(row.get("actual_owner")),
        "primaryOwner": text_value(row.get("actual_owner")) or text_value(row.get("owner")),
        "lockFlag": int(row.get("lock_flag") or 0),
        "stageCode": code,
        "stageName": STAGE_NAMES[code],
        "alertLevel": alert_level,
        "alertText": alert_text,
        "updateTime": row.get("update_time"),
    }
