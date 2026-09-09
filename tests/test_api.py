from io import BytesIO

from openpyxl import load_workbook


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.get_json()["data"]["status"] == "UP"
    assert response.get_json()["data"]["dataMode"] == "mock"


def test_team_tasks_and_summary(client):
    response = client.get("/api/tasks?scope=team&person=黄娜娟&page=1&pageSize=20")
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["pagination"]["total"] == 6
    assert data["summary"]["currentOpen"] == 6
    assert data["summary"]["unassigned"] == 2
    assert all(item["owner"] == "黄娜娟" for item in data["items"])


def test_my_tasks_respect_actual_owner(client):
    response = client.get("/api/tasks?scope=mine&person=马远尔")
    data = response.get_json()["data"]
    assert data["pagination"]["total"] == 2
    assert all(item["primaryOwner"] == "马远尔" for item in data["items"])


def test_assign_updates_mock_repository(client):
    response = client.post("/api/assign", json={
        "admIds": [101, 104],
        "actualOwner": "李志君",
        "actor": "黄娜娟",
    })
    assert response.status_code == 200
    assert response.get_json()["data"]["updatedCount"] == 2

    tasks = client.get("/api/tasks?scope=mine&person=李志君").get_json()["data"]["items"]
    assert {101, 104}.issubset({item["id"] for item in tasks})


def test_assign_rejects_invalid_ids(client):
    response = client.post("/api/assign", json={
        "admIds": [],
        "actualOwner": "李志君",
        "actor": "黄娜娟",
    })
    assert response.status_code == 400


def test_export_returns_valid_workbook(client):
    response = client.get("/api/export?scope=team&person=黄娜娟&source=CTRIP")
    assert response.status_code == 200
    assert response.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    workbook = load_workbook(BytesIO(response.data))
    assert workbook.sheetnames == ["ADM待处理"]
    sheet = workbook["ADM待处理"]
    assert sheet.max_row >= 5
    assert sheet["A1"].value == "ADM未结案订单核实清单"
    assert sheet.freeze_panes == "A5"
    assert sheet["A1"].fill.fgColor.rgb.endswith("17324D")
    headers = [cell.value for cell in sheet[4]]
    assert headers == [
        "ADM单号",
        "平台",
        "航司",
        "当前阶段",
        "票号",
        "ADM总金额",
        "主币种",
        "供应下发日期",
        "ADM最晚时限",
        "差异说明",
        "当前责任人",
        "是否确认",
        "实际责任人",
        "处理进度",
        "申诉状态",
        "申诉原因",
        "申诉结果",
        "结案处理结果",
    ]
    assert sheet["L5"].value is None
    assert sheet["N5"].value in {"已录入差异", "未录入差异"}
    assert len(sheet.data_validations.dataValidation) == 1


def test_wecom_send_is_disabled_by_default(client):
    response = client.post("/api/wecom/send", json={"person": "黄娜娟"})
    assert response.status_code == 503
    assert "尚未启用" in response.get_json()["message"]
