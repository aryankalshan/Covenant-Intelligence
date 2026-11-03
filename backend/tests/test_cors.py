import pytest
from fastapi.testclient import TestClient

from app.core.config import parse_cors_allowed_origins
from app.db.base import Base
from app.main import create_app


def preflight(client: TestClient, origin: str):
    return client.options(
        "/api/v1/agreements",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-dev-user",
        },
    )


def test_default_development_origins_allow_both_loopback_hosts(client):
    for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
        response = preflight(client, origin)
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
        assert "x-dev-user" in response.headers["access-control-allow-headers"].lower()


def test_default_origins_reject_unconfigured_vite_fallback_port(client):
    response = preflight(client, "http://localhost:5174")
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_frontend_port_configures_loopback_origins_and_custom_app_preflight(tmp_path):
    origins = parse_cors_allowed_origins(None, 5174)
    assert origins == ["http://localhost:5174", "http://127.0.0.1:5174"]
    app = create_app(
        database_url=f"sqlite:///{(tmp_path / 'cors.db').as_posix()}",
        storage_dir=tmp_path / "uploads",
        cors_allowed_origins=origins,
    )
    Base.metadata.create_all(app.state.engine)
    try:
        with TestClient(app) as client:
            for origin in origins:
                response = preflight(client, origin)
                assert response.status_code == 200
                assert response.headers["access-control-allow-origin"] == origin
    finally:
        app.state.engine.dispose()


@pytest.mark.parametrize("value", ["*", "https://example.test/path", "javascript://example.test"])
def test_cors_configuration_rejects_wildcard_or_non_origin_values(value):
    with pytest.raises(ValueError):
        parse_cors_allowed_origins(value, 5173)


def test_app_factory_rejects_unrestricted_wildcard_cors(tmp_path):
    with pytest.raises(ValueError):
        create_app(
            database_url=f"sqlite:///{(tmp_path / 'wildcard.db').as_posix()}",
            cors_allowed_origins=["*"],
        )
