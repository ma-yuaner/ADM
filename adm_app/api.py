from __future__ import annotations

from datetime import datetime

from flask import Blueprint, current_app, jsonify, request, send_file

from .errors import AppError
from .exporter import ExcelExportService
from .json_utils import json_ready


api = Blueprint("api", __name__, url_prefix="/api")


def _repository():
    return current_app.extensions["adm_repository"]


def _wecom():
    return current_app.extensions["wecom_service"]


def _success(data=None, message="success", status=200):
    return jsonify(json_ready({"success": True, "message": message, "data": data})), status


def _clean_text(name: str, max_length: int, required: bool = False) -> str:
    value = (request.args.get(name) or "").strip()
    if required and not value:
        raise AppError(f"{name}不能为空")
    if len(value) > max_length:
        raise AppError(f"{name}长度不能超过{max_length}")
    return value


def _positive_int(name: str, default: int, maximum: int) -> int:
    raw = request.args.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as error:
        raise AppError(f"{name}必须是整数") from error
    if value < 1 or value > maximum:
        raise AppError(f"{name}必须在1到{maximum}之间")
    return value


def _task_filters(export: bool = False) -> dict:
    return {
        "scope": _clean_text("scope", 10) or "mine",
        "person": _clean_text("person", 64),
        "source": _clean_text("source", 64),
        "alert": _clean_text("alert", 16),
        "stage": _clean_text("stage", 50),
        "search": _clean_text("search", 100),
        "page": 1 if export else _positive_int("page", 1, 100000),
        "page_size": 10000 if export else _positive_int("pageSize", 20, 200),
    }


@api.get("/health")
def health():
    state = _repository().health()
    return _success({
        "status": "UP",
        "dataMode": _repository().mode,
        "database": state["database"],
        "writeEnabled": state["writeEnabled"],
        "time": datetime.now(),
    })


@api.get("/config")
def config():
    return _success({
        "defaultPerson": current_app.config["DEFAULT_PERSON"],
        "dataMode": _repository().mode,
        "writeEnabled": _repository().health()["writeEnabled"],
        "wecomEnabled": _wecom().enabled,
    })


@api.get("/people")
def people():
    return _success({"items": _repository().people()})


@api.get("/tasks")
def tasks():
    return _success(_repository().list_tasks(_task_filters()))


@api.post("/assign")
def assign():
    body = request.get_json(silent=True) or {}
    ids = body.get("admIds")
    if not isinstance(ids, list) or not ids or len(ids) > 500:
        raise AppError("admIds必须是包含1到500个ID的数组")
    try:
        adm_ids = list(dict.fromkeys(int(value) for value in ids))
    except (TypeError, ValueError) as error:
        raise AppError("admIds只能包含整数") from error
    if any(value <= 0 for value in adm_ids):
        raise AppError("admIds只能包含正整数")

    actual_owner = str(body.get("actualOwner") or "").strip()
    actor = str(body.get("actor") or "").strip()
    if not actual_owner or len(actual_owner) > 64:
        raise AppError("actualOwner不能为空且长度不能超过64")
    if not actor or len(actor) > 64:
        raise AppError("actor不能为空且长度不能超过64")
    client_ip = (request.access_route[0] if request.access_route else request.remote_addr) or "0.0.0.0"
    result = _repository().assign(adm_ids, actual_owner, actor, client_ip)
    return _success(result, f"成功分配{result['updatedCount']}张ADM")


@api.get("/export")
def export_tasks():
    result = _repository().list_tasks(_task_filters(export=True))
    if result["pagination"]["total"] > 10000:
        raise AppError("单次导出不能超过10000张ADM，请增加筛选条件")
    exporter = ExcelExportService(current_app.config["EXPORT_PROFILES_FILE"])
    stream = exporter.build(result["items"])
    person = _clean_text("person", 64) or "全部人员"
    source = _clean_text("source", 64) or "全部数据源"
    filename = f"ADM待处理_{source}_{person}_{datetime.now():%Y%m%d_%H%M}.xlsx"
    return send_file(
        stream,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        max_age=0,
    )


@api.post("/wecom/send")
def send_wecom():
    body = request.get_json(silent=True) or {}
    person = str(body.get("person") or "").strip()
    if not person or len(person) > 64:
        raise AppError("person不能为空且长度不能超过64")
    result = _repository().list_tasks({
        "scope": "mine",
        "person": person,
        "source": "",
        "alert": "",
        "stage": "",
        "search": "",
        "page": 1,
        "page_size": 10000,
    })
    tasks = result["items"]
    if not tasks:
        raise AppError(f"{person}当前没有未结案ADM")
    exporter = ExcelExportService(current_app.config["EXPORT_PROFILES_FILE"])
    workbook = exporter.build(
        tasks,
        title=f"{person}—ADM未结案订单核实清单",
        subtitle=f"共{len(tasks)}张｜请核实订单归属、差异及申诉进度",
    )
    filename = f"ADM未结案核实_{person}_{datetime.now():%Y%m%d_%H%M}.xlsx"
    return _success(
        _wecom().send_excel(person, workbook, filename, len(tasks)),
        f"已发送{len(tasks)}张未结案ADM给{person}",
    )
