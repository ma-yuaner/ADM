from adm_app.domain import serialize_task
from adm_app.finance_diff import apply_finance_diff_status, FinanceDiffLookup
from sqlalchemy import create_engine, text
from decimal import Decimal
import pytest
from adm_app.errors import AppError


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


def test_finance_diff_progress_without_person_matching():
    rows = [
        _row("ADM-1"),
        _row("ADM-2", actual_owner="李四"),
        _row("ADM-3"),
    ]
    apply_finance_diff_status(rows, {
        "ADM-1": [{"business_ref_no": "ADM-1", "calculate_rate": -1, "duty_person": "其他人员"}],
        "ADM-2": [{"business_ref_no": "ADM-2", "calculate_rate": -1, "duty_person": ""}],
    })

    tasks = [serialize_task(row) for row in rows]
    assert [task["handlingProgress"] for task in tasks] == [
        "已录入差异",
        "已录入差异",
        "无差异单",
    ]
    assert tasks[0]["financeDiffCount"] == 1
    assert tasks[0]["financeDiffDutyPersons"] == ["其他人员"]


def test_multiple_expense_records_are_counted_without_person_matching():
    rows = [_row("ADM-1", actual_owner="李四")]
    apply_finance_diff_status(rows, {
        "ADM-1": [
            {"business_ref_no": "ADM-1", "calculate_rate": -1, "duty_person": "张三"},
            {"business_ref_no": "ADM-1", "calculate_rate": -1, "duty_person": "李四"},
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


def test_lookup_sql_uses_only_valid_expense_business_reference():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE order_info_diff_reason (business_ref_no TEXT, ota_order_no TEXT, duty_person TEXT, calculate_rate INTEGER, status INTEGER)"))
        connection.execute(text("INSERT INTO order_info_diff_reason VALUES ('ADM-1', 'NOT-ADM', '其他人员', -1, 1), ('ADM-2', 'ADM-1', '张三', 1, 1), ('ADM-3', 'ADM-3', '张三', -1, 0)"))
    rows = [_row("ADM-1"), _row("ADM-2"), _row("ADM-3")]
    FinanceDiffLookup(engine, chunk_size=1).attach(rows)
    assert [serialize_task(row)["handlingProgress"] for row in rows] == ["已录入差异", "无差异单", "无差异单"]
    engine.dispose()


def test_income_wrong_reference_and_invalid_records_are_excluded():
    rows = [_row("ADM-1")]
    apply_finance_diff_status(rows, {"ADM-1": [
        {"business_ref_no": "OTHER", "ota_order_no": "ADM-1", "calculate_rate": -1},
        {"business_ref_no": "ADM-1", "calculate_rate": 1},
        {"business_ref_no": "ADM-1", "calculate_rate": -1, "status": 0},
    ]})
    assert serialize_task(rows[0])["handlingProgress"] == "无差异单"
    apply_finance_diff_status(rows, {"ADM-1": [{"business_ref_no": "ADM-1", "calculate_rate": Decimal("-1.00")}]})
    assert serialize_task(rows[0])["handlingProgress"] == "已录入差异"


def test_query_failure_is_not_reported_as_no_difference():
    engine = create_engine("sqlite://")
    with pytest.raises(AppError):
        FinanceDiffLookup(engine).attach([_row("ADM-1")])
    engine.dispose()
