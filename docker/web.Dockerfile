# syntax=docker/dockerfile:1.7
# argon-web — Next.js 16 standalone. The client bundle calls relative /api/*,
# proxied to the api service by the next.config.mjs rewrite. SSR fetches read
# the same runtime NEXT_INTERNAL_API_BASE. argon web inlines NO NEXT_PUBLIC_*
# values — but next.config.mjs rewrites() is evaluated at BUILD time and frozen
# into the standalone server, so the client-side /api/* proxy target is a build
# arg (below), not runtime. Without it the rewrite bakes the localhost fallback
# and every browser /api/* call 500s in-container.
# Built natively on ubuntu-24.04-arm in release.yml for the arm64 mini.
#
# Local smoke (arm64 Docker host):
#   docker build -f docker/web.Dockerfile -t argon-web:dev .
#   docker run --rm -p 3001:3001 \
#     -e NEXT_INTERNAL_API_BASE=http://host.docker.internal:8400 argon-web:dev

FROM node:22-alpine AS builder
# next/font + sharp need libc6-compat on alpine.
RUN apk add --no-cache libc6-compat
WORKDIR /app/web

# Deps first for layer cache. web/ is a standalone project with its own lockfile
# (no repo-root package.json), so this is a single npm ci. legacy-peer-deps
# mirrors ci.yml / release.yml.
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund --legacy-peer-deps

# Build inputs. next.config.mjs pins outputFileTracingRoot to web/, so the
# standalone bundle emits at /app/web/.next/standalone/server.js (server.js +
# node_modules at the standalone root).
COPY web/ ./
# rewrites() bakes at build time — set the compose service-name target for the
# client-side /api/* proxy. SSR still reads this same value from runtime env.
# The launchd (non-Docker) build never sets this, keeping its correct localhost
# co-located default.
ARG NEXT_INTERNAL_API_BASE=http://api:8400
ENV NEXT_INTERNAL_API_BASE=$NEXT_INTERNAL_API_BASE
ENV NEXT_TELEMETRY_DISABLED=1
RUN npx next build

# ---- runtime ----
FROM node:22-alpine AS runtime
RUN apk add --no-cache libc6-compat tini
WORKDIR /app

# Next standalone does NOT bundle static/ or public/ — copy them alongside
# server.js (it resolves ./.next/static and ./public relative to itself).
COPY --from=builder /app/web/.next/standalone ./
COPY --from=builder /app/web/.next/static ./.next/static
COPY --from=builder /app/web/public ./public

ENV NODE_ENV=production \
    PORT=3001 \
    HOSTNAME=0.0.0.0 \
    NEXT_TELEMETRY_DISABLED=1

EXPOSE 3001
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["node", "server.js"]

LABEL org.opencontainers.image.source="https://github.com/moremeds/argon" \
      org.opencontainers.image.title="argon-web" \
      org.opencontainers.image.description="Argon Next.js terminal"
