from pathlib import Path

import pytest

from adm_app import create_app
from adm_app.repository import MockAdmRepository


@pytest.fixture()
def repository():
    return MockAdmRepository()


@pytest.fixture()
def app(repository, tmp_path):
    project_dir = Path(__file__).resolve().parents[1]
    return create_app({
        "TESTING": True,
        "REPOSITORY": repository,
        "DEFAULT_PERSON": "黄娜娟",
        "EXPORT_PROFILES_FILE": project_dir / "config" / "export_profiles.json",
        "RECOVERY_DB_PATH": tmp_path / "adm_recovery_test.db",
    })


@pytest.fixture()
def client(app):
    return app.test_client()
