from datetime import datetime, timedelta

from adm_app.domain import serialize_task
from adm_app.repository import attach_transfer_history


def test_transfer_history_uses_latest_transfer_and_post_transfer_lock():
    first = datetime(2026, 9, 8, 9, 0)
    latest = datetime(2026, 9, 9, 10, 0)
    rows = [{"id": 10}]
    logs = [
        {
            "business_obj_id": 10,
            "operator_datetime": first,
            "operator_name": "张组长",
            "operator_content": "【<b>实际责任人</b> 由 '' 修改为 '王一'】",
        },
        {
            "business_obj_id": 10,
            "operator_datetime": latest,
            "operator_name": "张组长",
            "operator_content": "【<b>实际责任人</b> 由 '王一' 修改为 '李二'】",
        },
        {
            "business_obj_id": 10,
            "operator_datetime": latest + timedelta(hours=1),
            "operator_name": "李二",
            "operator_content": "【<b>锁状态</b> 由 '未锁定' 修改为 '已锁定'】",
        },
    ]

    attach_transfer_history(rows, logs)

    assert rows[0]["transfer_count"] == 2
    assert rows[0]["last_transfer_time"] == latest
    assert rows[0]["last_transfer_from"] == "王一"
    assert rows[0]["last_transfer_to"] == "李二"
    assert rows[0]["transfer_awaiting_acceptance"] is False


def test_transfer_without_later_lock_is_pending_acceptance():
    transfer_time = datetime(2026, 9, 9, 10, 0)
    row = {
        "id": 10,
        "adm_no": "ADM-10",
        "owner": "张组长",
        "actual_owner": "李二",
        "lock_flag": 0,
        "adm_status": 0,
        "status": 1,
    }
    attach_transfer_history([row], [{
        "business_obj_id": 10,
        "operator_datetime": transfer_time,
        "operator_name": "张组长",
        "operator_content": "【<b>实际责任人</b> 由 '王一' 修改为 '李二'】",
    }])

    task = serialize_task(row, now=transfer_time + timedelta(hours=2))
    assert task["transferStatus"] == "转单后未接单"
    assert task["transferAgeHours"] == 2
