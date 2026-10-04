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

FROM python:3.13-slim AS uv-base

# uv pinned to a lock-compatible release. argon's uv.lock is `revision = 3`
# (produced by uv 0.11.x) — older uv (e.g. 0.5.x) cannot parse it, so pin to a
# 0.11 line. uv is a BUILD-only tool; it is not shipped to the runtime image.
COPY --from=ghcr.io/astral-sh/uv:0.11.17 /uv /uvx /usr/local/bin/
WORKDIR /app
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# ---- lock: the pinned dependency list, without uw_scan itself ----
# Every release bumps the version in pyproject.toml and uv.lock. The export
# below omits the project, so its text changes only when a dependency changes.
FROM uv-base AS lock
COPY pyproject.toml uv.lock README.md ./
RUN uv export --frozen --no-dev --extra postgres --no-emit-project \
        -o /requirements.txt

# ---- deps: the ~740 MB .venv ----
# Keyed only on requirements.txt, so a release that changes code but no
# dependency reuses this layer from the registry build cache (release.yml) and
# the mini pulls only the small src layer. Before this split, `src/` was copied
# ahead of `uv sync`, so every release shipped a new 220 MB compressed layer.
FROM uv-base AS deps
COPY --from=lock /requirements.txt /requirements.txt
RUN uv venv /app/.venv \
    && uv pip install --python /app/.venv/bin/python --no-deps \
        -r /requirements.txt

# ---- runtime ----
FROM python:3.13-slim AS runtime

# libpq5: psycopg runtime. curl: api compose healthcheck. tini: PID 1 for clean
# SIGTERM on `docker stop` / Watchtower recreate.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 ca-certificates curl tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=deps /app/.venv /app/.venv
# uw_scan runs from source on PYTHONPATH, the same as the editable install the
# old single-stage `uv sync` made (migrations live under src/uw_scan/storage/).
COPY src/ ./src/
# scripts/ is the ops escape hatch — backfills, gap-healer CLI, and the
# market-tide seed, run on demand via `docker-compose run --rm migrator …`.
COPY scripts/ ./scripts/
COPY pyproject.toml uv.lock README.md VERSION ./

# .venv on PATH → `uvicorn` and `python` resolve directly, no `uv run` prefix
# (uv is absent from this stage by design); PYTHONPATH → `uw_scan`.
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH=/app/src \
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
