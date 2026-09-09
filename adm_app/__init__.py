from __future__ import annotations

import logging
from pathlib import Path

from flask import Flask, jsonify, send_from_directory

from .api import api
from .config import AppConfig
from .errors import AppError
from .repository import create_repository


def create_app(config_overrides: dict | None = None) -> Flask:
    project_dir = Path(__file__).resolve().parents[1]
    settings = AppConfig.from_environment(project_dir)

    app = Flask(__name__, static_folder=str(project_dir / "web"), static_url_path="/assets")
    app.config.update(settings.to_flask_config())
    if config_overrides:
        app.config.update(config_overrides)

    logging.basicConfig(
        level=getattr(logging, app.config["LOG_LEVEL"], logging.INFO),
        format="%(asctime)s - %(levelname)s - [adm_assignment_demo] %(message)s",
    )

    repository = app.config.get("REPOSITORY") or create_repository(app.config, project_dir)
    app.extensions["adm_repository"] = repository
    app.register_blueprint(api)

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/favicon.ico")
    def favicon():
        return "", 204

    @app.errorhandler(AppError)
    def handle_app_error(error: AppError):
        return jsonify({"success": False, "message": error.message, "data": error.data}), error.status_code

    @app.errorhandler(404)
    def handle_not_found(_error):
        return jsonify({"success": False, "message": "接口或页面不存在", "data": None}), 404

    @app.errorhandler(Exception)
    def handle_unexpected(error: Exception):
        app.logger.exception("未处理异常: %s", error)
        return jsonify({"success": False, "message": "服务器内部错误", "data": None}), 500

    return app
