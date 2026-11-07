# Visit Counter

[![CI](https://github.com/matejaplazinic/visit-counter/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/matejaplazinic/visit-counter/actions/workflows/ci.yml)

A small Python/Flask HTTP service that counts visits in Redis. Docker Compose
runs both services; GitHub Actions checks the code and the real container stack.

## Architecture

```text
Browser / curl
      |
127.0.0.1:8080 (the only published port)
      |
app: Python + Flask + Waitress (non-root)
      |
      | Compose network, redis:6379
      v
redis: Redis + append-only persistence
      |
      v
redis-data: named volume mounted at /data
```

| Endpoint | Response |
| --- | --- |
| `GET /` | HTTP 200, `{"message":"Hello DevOps","host":"<container hostname>"}` |
| `GET /visits` | Increments the counter atomically and returns HTTP 200, `{"visits":1}` |
| `GET /health` | HTTP 200, `{"status":"ok"}` when Redis answers PING; otherwise HTTP 503, `{"status":"error"}` |

`/visits` also returns HTTP 503 with `{"status":"error"}` when Redis fails.
Every request, including errors and unknown routes, is logged to stdout.

## Prerequisites

- Git and a working Docker installation with Docker Compose v2 (`docker compose`).
- On Windows: Docker Desktop using Linux containers, preferably with WSL2/Ubuntu
  integration enabled. Run the Bash examples in Ubuntu or Git Bash.
- Bash and curl for the health-check script.
- Python 3.14.5 for development and automated checks outside Docker. Python is
  already included in the application image; it is not needed for the quick start.

## Quick start

Run from a Bash terminal, with Docker running:

```bash
git clone https://github.com/matejaplazinic/visit-counter.git
cd visit-counter
cp .env.example .env
docker compose up -d --build --wait
curl http://localhost:8080/
curl http://localhost:8080/visits
curl http://localhost:8080/visits
./scripts/healthcheck.sh http://localhost:8080
```

For an empty volume, the two visit responses contain `1` and `2`.
After the first build, the stack can also be started with `docker compose up -d`.

Inspect and stop the services:

```bash
docker compose ps
docker compose logs -f app
# Ctrl+C stops following logs; the containers keep running.
docker compose down
```

On PowerShell, copy configuration with `Copy-Item .env.example .env` and use
`curl.exe` for the examples. Execute the `.sh` script in Ubuntu or Git Bash.

### Configuration

Only `.env.example` is committed. Copy it to `.env` before starting Compose.
The application requires all three variables and fails at startup when they
are missing or invalid; host and port values are not hard-coded in Python.

| Variable | Example | Meaning |
| --- | --- | --- |
| `APP_PORT` | `8080` | App listener and published host port |
| `REDIS_HOST` | `redis` | Compose service DNS name; `localhost` would mean the app container itself |
| `REDIS_PORT` | `6379` | Redis listener and application connection port |

To change the app port, edit `APP_PORT` in `.env`, then run
`docker compose up -d --wait` and use the new port in curl and health-check URLs.
Compose injects these variables into the app and updates the published port.
The Redis command and its health check also follow `REDIS_PORT`.
`EXPOSE 8080` documents the default; it does not publish or set the listener port.

### Check persistence

After the first two visits above:

```bash
docker compose down
docker compose up -d --wait
curl http://localhost:8080/visits
# {"visits":3}
```

The named volume survives `down`; Redis writes its append-only files into it.
`--appendfsync everysec` balances write cost and durability: an abrupt host crash
can lose roughly the last second of writes. This is a demo, not a backup system.
**`docker compose down --volumes` deletes the stored counter.** Use it only for
an intentional reset.

### Demonstrate an outage and recovery

```bash
docker compose stop redis
curl -i http://localhost:8080/health
# HTTP 503 and {"status":"error"}
./scripts/healthcheck.sh http://localhost:8080
# Five failed attempts, exit code 1.
docker compose up -d --wait
./scripts/healthcheck.sh http://localhost:8080
# HTTP 200, exit code 0; the counter is preserved.
```

## Development and automated checks

Create an isolated Python environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m ruff format --check .
python -m pytest -q
docker build -t visit-counter .
```

On Windows, create the environment with `py -3.14 -m venv .venv` and invoke
`.venv\Scripts\python.exe` instead of `python`, or activate it with
`.\.venv\Scripts\Activate.ps1` if your PowerShell policy permits.

The 27 tests cover endpoint responses, atomic increment calls, configuration,
stdout request logs, Redis connection/timeout failures, a real refused Redis
connection, and the Bash script's retries and exit codes. Bash tests use a real
temporary HTTP server. They are skipped when Bash is unavailable; CI includes it.

Run full container verification from Linux/WSL with Docker and Bash available:

```bash
python scripts/verify_compose.py
```

This creates a randomly named, isolated Compose project using `.env.example`,
port `18080` for the app and `16379` for Redis internally. It checks:

- all endpoints against a real Redis instance;
- non-root application execution and no published Redis port;
- the actual Bash script against the application;
- counter persistence after `down` and container recreation;
- HTTP 503 during a Redis outage and recovery without losing the counter.

It removes **only that test project's** containers and volume when finished.
To avoid a busy test port, set `VERIFY_APP_PORT=18081` before running it.
`VERIFY_REDIS_PORT` can override its internal Redis port.

## CI

`.github/workflows/ci.yml` runs on every push and on pull requests targeting
`main`, in this order:

1. Check out the repository.
2. Set up Python and install dependencies.
3. Run Ruff lint and formatting checks.
4. Run the application and Bash tests.
5. Build the Docker image.
6. Verify the real Compose stack, persistence and outage recovery.

A failed step fails the job. Actions are pinned to commit SHAs, the token has
read-only repository permissions, and the job has a ten-minute timeout.

## Important decisions

- **Python + Flask:** a small API keeps the exercise focused on operations.
- **Waitress:** a WSGI server that runs on both Windows and Linux, so the same
  entry point works during local development and inside the container.
- **`python:3.14.5-slim`:** an official, explicitly versioned base with a small
  Debian userspace. Dependency installation precedes source copying for caching.
- **Non-root app user:** UID/GID 10001 limits privileges inside the app container.
- **`redis:8.10.3-alpine`:** an official, explicitly versioned Redis image.
- **Redis `INCR`:** increments atomically across concurrent requests. No automatic
  client retry is used because replaying an increment after a lost response can
  count it twice. Connection and socket timeouts are one second each.
- **Named volume + AOF:** persistence requires both durable files and Redis
  configuration that writes them. Recreating containers leaves the volume intact.
- **Readiness:** Compose waits for Redis's PING health check before starting the
  app. The app health check includes Redis availability. An unhealthy status by
  itself does not restart a container; `unless-stopped` handles process exits.
- **Network:** only the app is published, bound to host loopback for local use.
  Redis stays on the Compose network. No public cloud or external Redis is used.

## Problems encountered

- **CI runner migration:** `ubuntu-latest` resolved to Ubuntu 26.04, where
  `setup-python` could not find Python 3.14.5. Pinning `ubuntu-24.04` fixed the
  runner/Python compatibility issue. The original failed runs remain visible.
- **Windows/Linux script differences:** `.gitattributes` forces LF for scripts,
  and `healthcheck.sh` is committed with its executable bit. Git Bash allowed
  its HTTP tests to run on Windows before WSL was installed.
- **Docker unavailable on the development machine:** application and Bash tests
  ran locally; container build and integration verification run on the Linux CI
  runner. Local container execution still requires Docker Desktop/Engine.
- **Redis client retries:** the client's default backoff could delay failure
  responses and retry a write. Explicit zero retries keeps failure handling
  bounded and avoids automatically replaying an increment.

## What I would improve with more time

- Lock transitive dependencies and automate dependency/image updates.
- Add container vulnerability scanning and publish SHA-tagged images to GHCR.
- Add request metrics, structured logs and alerting.
- Add Redis authentication/TLS and a secret manager for a shared deployment.
- Measure a multi-stage build before claiming image-size savings.
- Add Kubernetes manifests after the Compose workflow is fully understood.

## AI tools and sources

OpenAI Codex was used to help plan and implement the application, configuration,
tests, CI, debugging and documentation. The repository records those changes in
incremental commits. The solution should be reviewed and understood before an
interview; the candidate must be able to explain and modify it independently.

References used:

- [Flask documentation](https://flask.palletsprojects.com/)
- [Docker Compose startup order](https://docs.docker.com/compose/how-tos/startup-order/)
- [Redis persistence](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/)
- [GitHub setup-python](https://github.com/actions/setup-python)
- [Waitress documentation](https://docs.pylonsproject.org/projects/waitress/en/stable/)

## Suggested interview demonstration

1. Start Compose and show both services becoming healthy.
2. Call `/` and explain the hostname; call `/visits` twice.
3. Recreate the containers and show that the counter continues.
4. Stop Redis, show `/health` returning 503, then recover it.
5. Explain Docker layers, the non-root user, volume and internal DNS.
6. Open the feature pull request and CI run.
7. Change `APP_PORT` through configuration and demonstrate the new URL.
