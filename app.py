"""HTTP visit counter backed by Redis."""

import logging
import os
import socket
import sys

from flask import Flask, jsonify, request
from redis import Redis
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry


def read_port(name: str) -> int:
    """Read a required TCP port and fail clearly on invalid configuration."""
    value = int(os.environ[name])
    if not 1 <= value <= 65535:
        raise ValueError(f"{name} must be between 1 and 65535")
    return value


def create_app(redis_client=None) -> Flask:
    """Build the application; allow a test double in place of Redis."""
    app = Flask(__name__)
    app.config["APP_PORT"] = read_port("APP_PORT")
    redis_host = os.environ["REDIS_HOST"]
    redis_port = read_port("REDIS_PORT")
    if not redis_host.strip():
        raise ValueError("REDIS_HOST must not be empty")

    client = (
        redis_client
        if redis_client is not None
        else Redis(
            host=redis_host,
            port=redis_port,
            socket_connect_timeout=1,
            socket_timeout=1,
            decode_responses=True,
            # Fail fast for health checks; do not replay a possibly applied INCR.
            retry=Retry(NoBackoff(), 0),
        )
    )

    # Flask's default handler uses stderr; send HTTP request logs to stdout.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    app.logger.handlers = [handler]
    app.logger.propagate = False
    app.logger.setLevel(logging.INFO)

    @app.after_request
    def log_request(response):
        app.logger.info("%s %s HTTP %s", request.method, request.path, response.status_code)
        return response

    @app.get("/")
    def index():
        return jsonify(message="Hello DevOps", host=socket.gethostname())

    @app.get("/visits")
    def visits():
        try:
            return jsonify(visits=client.incr("visits"))
        except RedisError:
            return jsonify(status="error"), 503

    @app.get("/health")
    def health():
        try:
            if client.ping():
                return jsonify(status="ok")
        except RedisError:
            pass
        return jsonify(status="error"), 503

    return app
