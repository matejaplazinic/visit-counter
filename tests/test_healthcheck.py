"""Exercise the Bash script with real HTTP responses and exit codes."""

import re
import shutil
import subprocess
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "healthcheck.sh"
BASH = shutil.which("bash")
if BASH is None:
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    if git_bash.exists():
        BASH = str(git_bash)

pytestmark = pytest.mark.skipif(BASH is None, reason="Bash is required for script tests")


def run_script(*arguments):
    return subprocess.run(
        [BASH, SCRIPT.as_posix(), *arguments],
        text=True,
        capture_output=True,
        timeout=50,
    )


@contextmanager
def health_server(statuses):
    paths = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append(self.path)
            self.send_response(statuses[min(len(paths) - 1, len(statuses) - 1)])
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", paths
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_missing_url_prints_usage():
    result = run_script()
    assert result.returncode == 1
    assert "Usage:" in result.stderr


def test_healthy_service_exits_after_first_attempt():
    with health_server([200]) as (url, paths):
        result = run_script(url + "/")
    assert result.returncode == 0
    assert paths == ["/health"]
    assert re.search(
        r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] Attempt 1/5 - HTTP 200", result.stdout
    )


def test_retry_recovers_after_unhealthy_response():
    with health_server([503, 200]) as (url, paths):
        result = run_script(url)
    assert result.returncode == 0
    assert paths == ["/health", "/health"]
    assert "Attempt 1/5 - HTTP 503" in result.stdout
    assert "Attempt 2/5 - HTTP 200" in result.stdout


def test_unhealthy_service_stops_after_five_attempts():
    with health_server([503]) as (url, paths):
        result = run_script(url)
    assert result.returncode == 1
    assert paths == ["/health"] * 5
    assert "Attempt 5/5 - HTTP 503" in result.stdout


def test_unreachable_service_is_retried():
    with health_server([200]) as (url, _):
        pass
    result = run_script(url)
    assert result.returncode == 1
    assert result.stdout.count("HTTP 000") == 5
