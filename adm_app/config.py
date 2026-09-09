from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AppConfig:
    host: str
    port: int
    debug: bool
    log_level: str
    data_mode: str
    write_enabled: bool
    default_person: str
    operator_id: int
    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_database: str
    export_profiles_file: Path

    @classmethod
    def from_environment(cls, project_dir: Path) -> "AppConfig":
        load_dotenv(project_dir / ".env")
        return cls(
            host=os.getenv("ADM_HOST", "0.0.0.0"),
            port=int(os.getenv("ADM_PORT", "5050")),
            debug=_bool_env("ADM_DEBUG"),
            log_level=os.getenv("ADM_LOG_LEVEL", "INFO").upper(),
            data_mode=os.getenv("ADM_DATA_MODE", "mock").strip().lower(),
            write_enabled=_bool_env("ADM_WRITE_ENABLED"),
            default_person=os.getenv("ADM_DEFAULT_PERSON", "黄娜娟"),
            operator_id=int(os.getenv("ADM_OPERATOR_ID", "0")),
            db_host=os.getenv("ADM_DB_HOST", ""),
            db_port=int(os.getenv("ADM_DB_PORT", "3306")),
            db_user=os.getenv("ADM_DB_USER", ""),
            db_password=os.getenv("ADM_DB_PASSWORD", ""),
            db_database=os.getenv("ADM_DB_DATABASE", "sibedb"),
            export_profiles_file=project_dir / os.getenv(
                "ADM_EXPORT_PROFILES", "config/export_profiles.json"
            ),
        )

    def to_flask_config(self) -> dict:
        return {
            "HOST": self.host,
            "PORT": self.port,
            "DEBUG": self.debug,
            "LOG_LEVEL": self.log_level,
            "DATA_MODE": self.data_mode,
            "WRITE_ENABLED": self.write_enabled,
            "DEFAULT_PERSON": self.default_person,
            "OPERATOR_ID": self.operator_id,
            "DB_HOST": self.db_host,
            "DB_PORT": self.db_port,
            "DB_USER": self.db_user,
            "DB_PASSWORD": self.db_password,
            "DB_DATABASE": self.db_database,
            "EXPORT_PROFILES_FILE": self.export_profiles_file,
        }
