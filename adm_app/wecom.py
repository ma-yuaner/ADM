from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

from .errors import AppError


class WeComRobotService:
    def __init__(
        self,
        enabled: bool,
        webhook_url: str,
        people_file: Path,
        people_json: str = "",
    ):
        self.webhook_url = webhook_url.strip()
        self.people = self._load_people(people_file, people_json)
        self.enabled = bool(enabled and self.webhook_url)

    @staticmethod
    def _load_people(path: Path, people_json: str) -> dict:
        if people_json:
            value = json.loads(people_json)
            if not isinstance(value, dict):
                raise RuntimeError("企业微信人员映射必须是JSON对象")
            return value
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise RuntimeError("企业微信人员映射必须是JSON对象")
        return value

    def _post_json(self, payload: dict) -> dict:
        try:
            response = requests.post(self.webhook_url, json=payload, timeout=20)
            response.raise_for_status()
        except requests.RequestException as error:
            raise AppError("企业微信网络请求失败，请检查服务器外网和Webhook", 502) from error
        result = response.json()
        if result.get("errcode") != 0:
            raise AppError(f"企业微信发送失败：{result.get('errmsg', '未知错误')}", 502)
        return result

    def send_excel(self, person: str, workbook, filename: str, task_count: int) -> dict:
        if not self.enabled:
            raise AppError("企业微信发送尚未启用，请配置机器人Webhook和发送开关", 503)
        query = parse_qs(urlparse(self.webhook_url).query)
        key = (query.get("key") or [""])[0]
        if not key:
            raise AppError("企业微信机器人Webhook格式不正确", 500)

        mapping = self.people.get(person) or {}
        if isinstance(mapping, str):
            mapping = {"mobile": mapping}
        user_id = str(mapping.get("user_id") or "").strip()
        mobile = str(mapping.get("mobile") or "").strip()
        text_payload = {
            "msgtype": "text",
            "text": {
                "content": (
                    f"【ADM未结案订单核实】\n"
                    f"处理人：{person}\n"
                    f"未结案订单：{task_count}张\n"
                    f"发送时间：{datetime.now():%Y-%m-%d %H:%M}\n"
                    "请下载附件逐项核实并及时反馈。"
                ),
                "mentioned_list": [user_id] if user_id else [],
                "mentioned_mobile_list": [mobile] if mobile else [],
            },
        }
        self._post_json(text_payload)

        content = workbook.getvalue()
        if len(content) > 20 * 1024 * 1024:
            raise AppError("企业微信附件超过20MB，请增加筛选条件后发送", 400)
        upload_url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media?key={key}&type=file"
        try:
            response = requests.post(
                upload_url,
                files={
                    "file": (
                        filename,
                        content,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
                timeout=60,
            )
            response.raise_for_status()
        except requests.RequestException as error:
            raise AppError("企业微信附件上传失败，请检查服务器外网和Webhook", 502) from error
        upload_result = response.json()
        if upload_result.get("errcode") != 0 or not upload_result.get("media_id"):
            raise AppError(f"企业微信附件上传失败：{upload_result.get('errmsg', '未知错误')}", 502)
        self._post_json({
            "msgtype": "file",
            "file": {"media_id": upload_result["media_id"]},
        })
        return {
            "person": person,
            "taskCount": task_count,
            "mentioned": bool(user_id or mobile),
        }
