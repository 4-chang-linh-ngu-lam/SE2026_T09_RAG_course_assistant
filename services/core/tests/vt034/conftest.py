import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.bootstrap import register_routers
from app.common.config import settings
from app.common.db import get_db
from app.common.errors import register_error_handlers
from app.common.security import create_access_token
from tests.notification.test_postgres import database, system  # noqa: F401, F811


@pytest.fixture
def client(system, monkeypatch):
    monkeypatch.setattr(settings, "secret_key", SecretStr("vt034-synthetic-key-" + "x" * 32))
    app = FastAPI()
    register_error_handlers(app)
    register_routers(app)

    def db():
        with system.factory() as session:
            yield session

    app.dependency_overrides[get_db] = db
    with TestClient(app) as result:
        yield result


def headers(user):
    return {"Authorization": "Bearer " + create_access_token(user.id, user.roles, 1)}
