"""Endpoint behavior and configuration without a running Redis server."""

import socket
from unittest.mock import Mock

import pytest
from redis.exceptions import ConnectionError, TimeoutError

from app import create_app


@pytest.fixture(autouse=True)
def configuration(monkeypatch):
    monkeypatch.setenv("APP_PORT", "8080")
    monkeypatch.setenv("REDIS_HOST", "redis")
    monkeypatch.setenv("REDIS_PORT", "6379")


@pytest.fixture
def redis_client():
    client = Mock()
    client.ping.return_value = True
    return client


@pytest.fixture
def client(redis_client):
    return create_app(redis_client).test_client()


def test_index_returns_message_and_hostname(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json["message"] == "Hello DevOps"
    assert response.json["host"]


def test_visits_increments_counter(client, redis_client):
    redis_client.incr.side_effect = [1, 2]
    for expected in (1, 2):
        response = client.get("/visits")
        assert response.status_code == 200
        assert response.json == {"visits": expected}
    assert redis_client.incr.call_count == 2
    redis_client.incr.assert_called_with("visits")


def test_health_checks_redis(client, redis_client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok"}
    redis_client.ping.assert_called_once_with()


@pytest.mark.parametrize("error", [ConnectionError, TimeoutError])
@pytest.mark.parametrize("endpoint,operation", [("/health", "ping"), ("/visits", "incr")])
def test_redis_failure_returns_503(client, redis_client, error, endpoint, operation):
    getattr(redis_client, operation).side_effect = error("Redis unavailable")
    response = client.get(endpoint)
    assert response.status_code == 503
    assert response.json == {"status": "error"}


def test_unsuccessful_ping_returns_503(client, redis_client):
    redis_client.ping.return_value = False
    assert client.get("/health").status_code == 503


def test_requests_are_logged_to_stdout(capsys, redis_client):
    client = create_app(redis_client).test_client()
    client.get("/")
    client.get("/missing")
    output = capsys.readouterr().out
    assert "GET / HTTP 200" in output
    assert "GET /missing HTTP 404" in output


def test_port_comes_from_environment(monkeypatch, redis_client):
    monkeypatch.setenv("APP_PORT", "9090")
    assert create_app(redis_client).config["APP_PORT"] == 9090


@pytest.mark.parametrize("name", ["APP_PORT", "REDIS_HOST", "REDIS_PORT"])
def test_required_configuration(monkeypatch, name, redis_client):
    monkeypatch.delenv(name)
    with pytest.raises(KeyError, match=name):
        create_app(redis_client)


@pytest.mark.parametrize("name", ["APP_PORT", "REDIS_PORT"])
@pytest.mark.parametrize("value", ["0", "65536", "invalid"])
def test_invalid_port_is_rejected(monkeypatch, name, value, redis_client):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        create_app(redis_client)


def test_empty_redis_host_is_rejected(monkeypatch, redis_client):
    monkeypatch.setenv("REDIS_HOST", " ")
    with pytest.raises(ValueError, match="REDIS_HOST"):
        create_app(redis_client)


@pytest.mark.parametrize("endpoint", ["/health", "/visits"])
def test_real_redis_client_handles_connection_refused(monkeypatch, endpoint):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    monkeypatch.setenv("REDIS_HOST", "127.0.0.1")
    monkeypatch.setenv("REDIS_PORT", str(port))
    response = create_app().test_client().get(endpoint)
    assert response.status_code == 503
    assert response.json == {"status": "error"}
