from adm_app.domain import serialize_task
from adm_app.finance_diff import apply_finance_diff_status, responsibility_matches


def _row(adm_no: str, owner: str = "张三", actual_owner: str = "") -> dict:
    return {
        "id": 1,
        "adm_no": adm_no,
        "owner": owner,
        "actual_owner": actual_owner,
        "diff_detail_reason": "原有差异说明",
        "adm_status": 0,
        "lock_flag": 0,
    }


def test_finance_diff_progress_three_states():
    rows = [
        _row("ADM-1"),
        _row("ADM-2", actual_owner="李四"),
        _row("ADM-3"),
    ]
    apply_finance_diff_status(rows, {
        "ADM-1": [{"create_user_name": "张三", "duty_person": ""}],
        "ADM-2": [{"create_user_name": "张三", "duty_person": ""}],
    })

    tasks = [serialize_task(row) for row in rows]
    assert [task["handlingProgress"] for task in tasks] == [
        "已录入差异",
        "有差异单不是责任人录入",
        "无差异单",
    ]
    assert tasks[0]["financeDiffCount"] == 1
    assert tasks[0]["financeDiffCreators"] == ["张三"]


def test_any_matching_creator_marks_the_adm_as_recorded():
    rows = [_row("ADM-1", actual_owner="李四")]
    apply_finance_diff_status(rows, {
        "ADM-1": [
            {"create_user_name": "张三", "duty_person": ""},
            {"create_user_name": "李四", "duty_person": ""},
        ]
    })

    task = serialize_task(rows[0])
    assert task["handlingProgress"] == "已录入差异"
    assert task["financeDiffCount"] == 2


def test_original_progress_is_preserved_when_finance_check_disabled():
    with_description = serialize_task(_row("ADM-1"))
    without_description = _row("ADM-2")
    without_description["diff_detail_reason"] = ""

    assert with_description["handlingProgress"] == "已录入差异"
    assert serialize_task(without_description)["handlingProgress"] == "未录入差异"
    assert with_description["financeDiffChecked"] is False


def test_responsibility_match_accepts_departure_annotation_but_not_other_person():
    assert responsibility_matches("刘佳鑫", "刘佳鑫/已离职") is True
    assert responsibility_matches("李四", "张三/已离职") is False
