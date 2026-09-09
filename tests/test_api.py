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
    workbook = load_workbook(BytesIO(response.data), read_only=True)
    assert workbook.sheetnames == ["CTRIP"]
    sheet = workbook["CTRIP"]
    assert sheet.max_row >= 2
    assert sheet["A1"].value == "携程订单号"
