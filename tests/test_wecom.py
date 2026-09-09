from io import BytesIO
from pathlib import Path

from adm_app.wecom import WeComRobotService


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_wecom_sends_text_with_mention_then_excel(monkeypatch):
    people_file = Path(__file__).resolve().parents[1] / "config" / "wecom_people.json"
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        if "upload_media" in url:
            return FakeResponse({"errcode": 0, "media_id": "media-1"})
        return FakeResponse({"errcode": 0, "errmsg": "ok"})

    monkeypatch.setattr("adm_app.wecom.requests.post", fake_post)
    service = WeComRobotService(
        True,
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test-key",
        people_file,
        '{"黄娜娟":{"mobile":"13800000000"}}',
    )
    result = service.send_excel("黄娜娟", BytesIO(b"xlsx"), "ADM.xlsx", 3)

    assert result == {"person": "黄娜娟", "taskCount": 3, "mentioned": True}
    assert len(calls) == 3
    assert calls[0][1]["json"]["text"]["mentioned_mobile_list"] == ["13800000000"]
    assert calls[1][1]["files"]["file"][0] == "ADM.xlsx"
    assert calls[2][1]["json"]["msgtype"] == "file"
