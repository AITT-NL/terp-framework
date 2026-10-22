# Backend image for the Terp app (dev workbench). The same image backs the one-shot
# migrate + seed services and the api server (see docker-compose.yml).
FROM python:3.14-slim

# uv: fast workspace-aware installs for the generated app image.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Install the app + its Terp dependencies (from pyproject.toml), plus the ASGI server and the
# Postgres driver. Editable, so `docker compose watch` picks up source edits under --reload.
# When the checkout vendors pre-release terp-* wheels (.terp-dist/, staged by Terp Studio
# before the packages are published) the install resolves them from there; otherwise the
# package registry is used. The .dockerignore keeps host-only trees out of the context.
COPY . .
RUN if [ -d .terp-dist/wheels ]; then \
        uv pip install --system --no-cache --find-links .terp-dist/wheels -e . "uvicorn[standard]" "psycopg[binary]"; \
    else \
        uv pip install --system --no-cache -e . "uvicorn[standard]" "psycopg[binary]"; \
    fi

# Run as a non-root user that owns the (sync-mutable) source. `var/files` is the files
# capability's default storage root, and it is created here so that user owns it: a named
# volume mounted at a path the image does not have is created owned by root, and an
# upload into it then fails with a permission error.
RUN useradd --create-home --uid 10001 appuser && mkdir -p /app/var/files && chown -R appuser /app
USER appuser

EXPOSE 8000
# --timeout-graceful-shutdown bounds the wait for in-flight tasks; unset, uvicorn waits
# forever, and a realtime stream never ends on its own. Eight seconds sits under Compose's
# ten-second default stop grace, so the process exits on its own terms instead of being killed.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "8"]
