from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.common import db
from app.main import app
from app.modules.health import router as health_module


def test_liveness() -> None:
    response = TestClient(app).get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "live"}


def test_readiness_success(monkeypatch):
    monkeypatch.setattr(health_module, "ping_database", lambda: None)
    response = TestClient(app).get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "db": "connected"}


def test_readiness_db_failure_does_not_break_liveness(monkeypatch):
    def unavailable():
        raise OperationalError("SELECT 1", {}, RuntimeError("private DB detail"))

    monkeypatch.setattr(health_module, "ping_database", unavailable)
    client = TestClient(app)
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert "private" not in response.text
    assert response.json()["error"]["correlation_id"] == response.headers["X-Correlation-ID"]
    assert client.get("/health/live").status_code == 200


@pytest.mark.parametrize("usable", [None, False, True])
def test_ping_checks_core_schema_permission(monkeypatch, usable):
    connection = MagicMock()
    connection.scalar.return_value = usable
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection
    monkeypatch.setattr(db, "engine", engine)
    if usable:
        db.ping_database()
    else:
        with pytest.raises(db.SQLAlchemyError):
            db.ping_database()
    assert str(connection.execute.call_args.args[0]) == "SELECT 1"
    assert "has_schema_privilege" in str(connection.scalar.call_args.args[0])
