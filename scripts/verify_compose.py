"""Verify the real stack in an isolated Compose project, then remove test data."""

import json
import os
import subprocess
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    environment = os.environ.copy()
    # Non-default ports also exercise environment-based configuration.
    environment.update(
        APP_PORT=environment.get("VERIFY_APP_PORT", "18080"),
        REDIS_HOST="redis",
        REDIS_PORT=environment.get("VERIFY_REDIS_PORT", "16379"),
    )
    project = "visit-counter-check-" + uuid.uuid4().hex[:8]
    command = [
        "docker",
        "compose",
        "--project-name",
        project,
        "--env-file",
        ".env.example",
    ]

    def compose(*arguments, check=True):
        return subprocess.run(
            [*command, *arguments],
            cwd=ROOT,
            env=environment,
            text=True,
            check=check,
            capture_output=True,
            timeout=180,
        )

    base_url = "http://127.0.0.1:" + environment["APP_PORT"]

    def expect(path, status, body=None):
        try:
            response = urllib.request.urlopen(base_url + path, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            actual = json.load(response)
            if response.status != status or (body is not None and actual != body):
                raise AssertionError(f"{path}: unexpected HTTP {response.status}: {actual}")
        print(f"PASS {path}: HTTP {status} {actual}", flush=True)
        return actual

    try:
        compose("up", "--build", "-d", "--wait", "--wait-timeout", "90")
        greeting = expect("/", 200)
        assert greeting["message"] == "Hello DevOps" and greeting["host"]
        expect("/health", 200, {"status": "ok"})
        expect("/visits", 200, {"visits": 1})
        expect("/visits", 200, {"visits": 2})

        uid = compose("exec", "-T", "app", "id", "-u").stdout.strip()
        assert uid != "0", "The application must not run as root"
        config = json.loads(compose("config", "--format", "json").stdout)
        assert not config["services"]["redis"].get("ports"), "Redis must not publish a port"

        subprocess.run(
            ["bash", "scripts/healthcheck.sh", base_url],
            cwd=ROOT,
            check=True,
            timeout=45,
        )

        compose("down")
        compose("up", "-d", "--wait", "--wait-timeout", "90")
        expect("/visits", 200, {"visits": 3})
        print("PASS counter survives container removal and recreation", flush=True)

        compose("stop", "redis")
        expect("/health", 503, {"status": "error"})
        expect("/visits", 503, {"status": "error"})
        expect("/", 200)
        compose("up", "-d", "--wait", "--wait-timeout", "90")
        expect("/health", 200, {"status": "ok"})
        expect("/visits", 200, {"visits": 4})
        print("PASS Redis outage and recovery", flush=True)
    except Exception:
        logs = compose("logs", "--no-color", check=False)
        print(logs.stdout, logs.stderr, flush=True)
        raise
    finally:
        # Only remove resources belonging to this randomly named test project.
        result = compose("down", "--volumes", "--remove-orphans", check=False)
        if result.returncode:
            print(result.stderr, flush=True)


if __name__ == "__main__":
    main()
