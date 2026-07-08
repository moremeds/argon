# syntax=docker/dockerfile:1.7
# argon-app — one Python image for api / workers / ws-consumer / migrator.
# The api/workers/ws-consumer/migrator all run the same uw_scan package, so
# each compose service just overrides `command:` (see docker-compose.yml).
# Built natively on ubuntu-24.04-arm in release.yml for the arm64 mini.
# Reaches host Postgres + xenon/apex via host.docker.internal (set in the
# container .env, NOT baked here).
#
# Local smoke (arm64 Docker host):
#   docker build -f docker/app.Dockerfile -t argon-app:dev .
#   docker run --rm --env-file .env argon-app:dev \
#     python -m uw_scan.storage.migrate_runner

FROM python:3.13-slim AS builder

# uv pinned to a lock-compatible release. argon's uv.lock is `revision = 3`
# (produced by uv 0.11.x) — older uv (e.g. 0.5.x) cannot parse it, so pin to a
# 0.11 line. uv is a BUILD-only tool; it is not shipped to the runtime image.
COPY --from=ghcr.io/astral-sh/uv:0.11.17 /uv /uvx /usr/local/bin/

WORKDIR /app

# Lock + manifest + README (setuptools reads `readme`) + source, then a frozen,
# no-dev install with the postgres extra (psycopg). uv builds .venv with an
# editable install of uw_scan pointing at /app/src (migrations included, they
# live under src/uw_scan/storage/migrations/).
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
RUN uv sync --frozen --no-dev --extra postgres

# ---- runtime ----
FROM python:3.13-slim AS runtime

# libpq5: psycopg runtime. curl: api compose healthcheck. tini: PID 1 for clean
# SIGTERM on `docker stop` / Watchtower recreate.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 ca-certificates curl tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
# scripts/ is the ops escape hatch — backfills, gap-healer CLI, and the
# market-tide seed, run on demand via `docker-compose run --rm migrator …`.
COPY scripts/ ./scripts/
COPY pyproject.toml uv.lock README.md VERSION ./

# .venv on PATH → `uvicorn`, `python`, and the uw_scan package resolve directly,
# no `uv run` prefix (uv is absent from this stage by design).
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

ENTRYPOINT ["/usr/bin/tini", "--"]
# Sane default; every compose service overrides `command:`. No HEALTHCHECK here
# — the same image runs HTTP-less workers; the api/web healthchecks live in
# compose where they apply to the right service.
CMD ["uvicorn", "uw_scan.api.server:app", "--host", "0.0.0.0", "--port", "8400"]

LABEL org.opencontainers.image.source="https://github.com/moremeds/argon" \
      org.opencontainers.image.title="argon-app" \
      org.opencontainers.image.description="Argon FastAPI + APScheduler workers + spot-WS consumer"
