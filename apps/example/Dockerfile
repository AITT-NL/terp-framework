# Terp example — backend image for the dev workbench.
#
# Built from the REPOSITORY ROOT (docker-compose.yml sets `context: ../..`), because it
# installs the framework packages from packages/ and runs the app code from apps/example.
# The same image backs the one-shot `migrate` + `seed` services and the `api` server.
FROM python:3.13-slim

# uv: fast, workspace-aware installs for the example app image.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONPATH=/workspace

WORKDIR /workspace

# Install the framework packages editable (so `docker compose watch` picks up source edits
# under uvicorn --reload without a rebuild) plus the ASGI server and the Postgres driver.
COPY packages/ packages/
RUN uv pip install --system --no-cache \
    -e packages/backend/core \
    -e packages/backend/arch \
    -e packages/backend/migrations \
    -e packages/backend/capabilities/auth \
    -e packages/backend/capabilities/identity \
    -e packages/backend/capabilities/tenancy \
    -e packages/backend/capabilities/access \
    -e packages/backend/capabilities/audit \
    -e packages/backend/capabilities/eventbus \
    -e packages/backend/capabilities/files \
    -e packages/backend/capabilities/groups \
    -e packages/backend/capabilities/users \
    -e packages/backend/capabilities/outbox \
    -e packages/backend/capabilities/realtime \
    -e packages/backend/capabilities/redis \
    -e packages/backend/capabilities/oidc \
    -e packages/backend/capabilities/webhooks \
    -e packages/backend/cli \
    uvicorn "psycopg[binary]"

# The example app code runs on PYTHONPATH (mirrors the pytest `pythonpath = apps/example`).
COPY apps/example/app app
COPY apps/example/control_plane control_plane

# Drop privileges: run as a non-root user that owns the (sync-mutable) workspace.
RUN useradd --create-home --uid 10001 terp && chown -R terp /workspace
USER terp

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
