# Backend image for the Terp app (dev workbench). The same image backs the one-shot
# migrate + seed services and the api server (see docker-compose.yml).
FROM python:3.13-slim

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
        uv pip install --system --no-cache --find-links .terp-dist/wheels -e . uvicorn "psycopg[binary]"; \
    else \
        uv pip install --system --no-cache -e . uvicorn "psycopg[binary]"; \
    fi

# Run as a non-root user that owns the (sync-mutable) source.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
