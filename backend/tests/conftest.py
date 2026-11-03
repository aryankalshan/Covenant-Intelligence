import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import pytest
from fastapi.testclient import TestClient

from app.db.base import Base
from app.main import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        storage_dir=tmp_path / "uploads",
    )
    # Tests create their isolated schema directly; production schema changes go through Alembic.
    Base.metadata.create_all(app.state.engine)
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.state.engine.dispose()


@pytest.fixture
def dev_headers():
    return {"X-Dev-User": "contributor"}
