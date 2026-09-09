from datetime import datetime, timedelta

from adm_app.domain import appeal_result_name, appeal_submission_name, alert_info, stage_code


def test_stage_prefers_locked_pending_decision():
    row = {"adm_status": 0, "appeal_status": None, "appeal_result": None, "owner": "张三", "lock_flag": 1}
    assert stage_code(row) == "LOCKED_PENDING_DECISION"


def test_overdue_is_p0():
    now = datetime(2026, 9, 9, 12, 0)
    row = {
        "adm_status": 0, "appeal_status": None, "appeal_result": None,
        "owner": "张三", "lock_flag": 1,
        "adm_deadline": now - timedelta(minutes=1), "update_time": now,
    }
    assert alert_info(row, now) == ("P0", "超过截止时间")


def test_export_appeal_names():
    assert appeal_submission_name({"adm_status": 0, "appeal_status": None}) == "待提交"
    assert appeal_submission_name({"adm_status": 1, "appeal_status": 0}) == "已提交"
    assert appeal_submission_name({"adm_status": 2, "appeal_status": 1}) == "不提交可结案"
    assert appeal_result_name(0) == "申诉成功"
    assert appeal_result_name(1) == "申诉失败"
    assert appeal_result_name(None) == ""
