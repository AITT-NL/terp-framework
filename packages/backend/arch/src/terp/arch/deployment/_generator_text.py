"""The generator's fixed text: its paths, its defaults and the files it writes as they stand.

Everything here is framework text, never a declaration value: the two Dockerfiles (which take
no declaration input in this version, ADR 0187), the profile's own comments, and the fixed
interpolations an executor's escape audit accepts (:mod:`terp.arch.deployment.generator`).
"""

from __future__ import annotations

BACKEND_DOCKERFILE = "Dockerfile.prod"
FRONTEND_DOCKERFILE = "frontend/Dockerfile.prod"
PROFILE = "docker-compose.prod.yml"

#: Every path the generator owns. A path the declaration renders nothing for is absent.
OWNED_PATHS = (BACKEND_DOCKERFILE, FRONTEND_DOCKERFILE, PROFILE)

#: The only profile a generated app has: the generator renders one file, with no override.
PROFILE_FILE = PROFILE

#: The frontend lock a ``web`` unit is built from; the caller says whether it exists.
FRONTEND_LOCK = "frontend/package-lock.json"

#: Where the backend image runs the app from, and so where a ``var/`` mount lands.
APP_ROOT = "/srv"

#: The one mount path this version renders: the files capability's default storage root,
#: which the backend image already makes as a mount point owned by its user.
MOUNT_PATH = "var/files"

#: The variable the profile's image names read their per-release tag from (ADR 0185 decision
#: 6). This is the one place it is spelled: everything that sets or reads it imports the name.
RELEASE_TAG_VARIABLE = "TERP_RELEASE_TAG"

#: The tag, ``:?``-required like ``SECRET_KEY``: with it unset compose stops instead of
#: falling back to a fixed tag a build would overwrite, so a release's images stay on the
#: host beside the next one's and the previous release can be started again. The message is
#: fixed text, so an executor's escape audit matches the whole scalar.
RELEASE_TAG_SEAM = (
    f"${{{RELEASE_TAG_VARIABLE}:?{RELEASE_TAG_VARIABLE} is required, one new image tag per release}}"
)

#: The migration step, rendered on the one ``one-shot`` unit that declares no command.
MIGRATION_STEP = ("terp", "migrate", "upgrade", "--app-root", "/srv/app")

#: The command a role runs when its unit declares none. An ``api`` and a ``web`` unit run
#: their image's own; a ``kind`` unit runs its datastore's.
DEFAULT_COMMANDS = {
    "worker": ("terp", "jobs", "worker", "--forever"),
    "scheduler": ("terp", "jobs", "scheduler"),
}

#: The fixed probe an ``api`` unit's healthcheck runs, with its liveness path as the one
#: argument: the path is data, never code, and the leading ``/`` the schema requires keeps
#: it from moving the host.
HEALTH_PROBE = (
    "import sys, urllib.request; "
    "urllib.request.urlopen('http://127.0.0.1:8000' + sys.argv[1])"
)

#: The fixed probe a unit whose command writes a heartbeat runs (ADR 0191), with the role
#: whose heartbeat it reads as the one argument. It reads the file ``terp jobs worker
#: --forever`` or ``terp jobs scheduler`` writes in the container's temporary directory
#: (``terp.cli.heartbeat``), prints the heartbeat's age and its bound as one JSON line,
#: which a deploy tool reads back from the container's health log, and fails when the age
#: is past the bound the writer declared or there is no heartbeat to read. Standard library
#: only: no HTTP, no database, no import of the app.
HEARTBEAT_PROBE = (
    "import json, os, sys, tempfile, time; "
    "beat = json.load(open(os.path.join(tempfile.gettempdir(), "
    "'terp-' + sys.argv[1] + '.heartbeat'))); "
    "age = time.time() - beat['at']; "
    "print(json.dumps({'heartbeat': sys.argv[1], 'age_seconds': round(age, 1), "
    "'stale_after_seconds': beat['stale_after']})); "
    "sys.exit(age > beat['stale_after'])"
)


def heartbeat_role(command: tuple[str, ...] | None) -> str | None:
    """The heartbeat a unit running *command* writes: ``worker``, ``scheduler`` or none.

    ``terp jobs worker --forever`` and ``terp jobs scheduler`` write one (ADR 0191). A single
    drain, a companion or any other command does not, and a unit running one gets no check:
    a check of a heartbeat nobody writes could only ever fail.
    """
    if command is None:
        return None
    if command[:3] == ("terp", "jobs", "worker") and "--forever" in command[3:]:
        return "worker"
    if command[:3] == ("terp", "jobs", "scheduler"):
        return "scheduler"
    return None

#: The way out of every refusal.
OWN_REMEDY = (
    'Or declare "build": "own" and maintain the build files by hand: '
    "the generator renders only what it can render faithfully."
)

HEADER = (
    "# Rendered by `terp deployment render` from deployment.json (ADR 0187). Where "
    "deployment.json\n"
    '# says "build": "generated" this file is the generator\'s: change deployment.json and '
    "render\n"
    '# again, never this file. Under "build": "own" it is the app\'s to change.\n'
)

_BASE_COMMENT = (
    "# Every base is pinned by digest from terp-arch's base-image table, never by a tag that\n"
    "# can move between two builds of one commit; the tag each digest was read from stands\n"
    "# above its FROM, and a framework release moves them.\n"
)

_BACKEND_DOCKERFILE = (
    HEADER
    + """#
# Production backend image (ADR 0062). It installs exactly the committed lock: every
# dependency, the ASGI server and the Postgres driver included, at the version and hash
# uv.lock records, and the build refuses a lock that has drifted from pyproject.toml
# instead of resolving again. No editable installs, no source tree beyond the two roots
# `terp migrate` reads, no build tooling, no uv. The same image backs every unit built
# from the checkout but the web tier; bootstrap the first admin with `terp user create`
# (never `terp seed`, which refuses ENVIRONMENT=production). The dev workbench keeps its
# own Dockerfile.
#
"""
    + _BASE_COMMENT
    + """#
# Layered so an edit to the app rebuilds only the app: the manifest and the lock first,
# the dependencies installed from them in a layer of their own, the app last. The
# runtime image is the same three parts, a base, the locked dependencies and the app, so
# a release that changes only code ships a new app layer over an unchanged dependency
# layer.
#
# Compiled to bytecode at build time, each part in its own layer: the process runs as a
# user who cannot write the environment, so bytecode it does not ship it compiles again on
# every start, which made importing the app several times slower. Checked-hash bytecode
# (PEP 552, `--invalidation-mode checked-hash`) records a hash of its source instead of a
# time, so no file's mtime reaches it, and the interpreter still refuses a .pyc whose
# source has changed.
#
# No BuildKit cache mounts, on purpose: a release build must never read a cache that a
# development build wrote. The layers are the cache, keyed by their inputs. The image does
# need BuildKit, the builder of every `docker compose` build and of `docker build` since
# Docker Engine 23, for the `RUN --mount=from=` bind mounts below and for a COPY pattern
# that may match nothing.

# The uv binary, named once so a stage can mount it without the runtime image keeping it.
# @@UV_TAG@@
FROM @@UV@@ AS uv

# --- Stage 1: the locked dependencies -------------------------------------------------
# @@PYTHON_TAG@@
FROM @@PYTHON@@ AS deps

COPY --from=uv /uv /bin/uv

# The environment is built where the runtime runs it from (/srv/.venv), on this image's
# own interpreter, so the copy below needs no relocation and no interpreter download.
ENV UV_PROJECT_ENVIRONMENT=/srv/.venv \\
    UV_PYTHON_DOWNLOADS=never \\
    UV_NO_CACHE=1 \\
    UV_LINK_MODE=copy

WORKDIR /build

# Only what decides the dependencies: the manifest, the lock, and the pre-release terp-*
# wheels a checkout vendors under .terp-dist/wheels before the packages are published
# (the lock names them by that relative path). The brackets make the second COPY a
# pattern, so a checkout with no vendored wheels copies nothing.
COPY pyproject.toml uv.lock ./
COPY .terp-dis[t]/wheel[s] .terp-dist/wheels/
# Exactly the lock's runtime set: no dev group, nothing the lock does not name, and a
# refusal ("The lockfile at `uv.lock` needs to be updated") instead of a fresh
# resolution when pyproject.toml and the lock disagree. `uv lock` is the fix.
RUN uv sync --locked --no-dev --no-install-project
RUN /srv/.venv/bin/python -m compileall -q -j 0 --invalidation-mode checked-hash /srv/.venv/lib

# --- Stage 2: the app wheel -----------------------------------------------------------
# The whole context, which .dockerignore keeps free of secrets, local databases, caches
# and dependency trees. The wheel holds exactly the packages pyproject.toml ships
# ([tool.hatch.build.targets.wheel]), so a companion root needs no line here.
FROM deps AS app
COPY . .
RUN uv build --wheel --out-dir /dist .

# --- Stage 3: minimal runtime ---------------------------------------------------------
# @@PYTHON_TAG@@
FROM @@PYTHON@@

ENV PYTHONUNBUFFERED=1 \\
    PYTHONDONTWRITEBYTECODE=1 \\
    VIRTUAL_ENV=/srv/.venv \\
    PATH="/srv/.venv/bin:$PATH"

WORKDIR /srv

# The user the process runs as, created before anything the app changes, so this layer is
# reused as well. The runtime never writes to the image filesystem (read-only-FS safe).
# `var/files`, the files capability's default storage root, is a mount point and not image
# filesystem: it exists, owned by that user, so a volume mounted there can be written (a
# named volume mounted at a path the image does not have is created owned by root).
RUN useradd --create-home --uid 10001 appuser \\
    && mkdir -p /srv/var/files && chown appuser /srv/var/files

# The dependency layer: reused until pyproject.toml, uv.lock or a vendored wheel changes.
COPY --from=deps /srv/.venv /srv/.venv
# The app layers, last: the wheel, with no dependencies of its own to resolve (the lock
# already installed them), from mounts that leave neither the wheel nor uv in the image;
# then the two source roots `terp migrate --app-root` and the app ref resolve from /srv.
RUN --mount=from=uv,source=/uv,target=/bin/uv \\
    --mount=from=app,source=/dist,target=/dist \\
    uv pip install --python /srv/.venv/bin/python --no-deps --no-cache /dist/*.whl
COPY app app
COPY control_plane control_plane
# The two source roots are what the processes import the app from, so they are compiled
# the same way. A package the wheel installs beside them (a companion's) compiles when it
# is first imported.
RUN python -m compileall -q -j 0 --invalidation-mode checked-hash app control_plane

# Drop privileges.
USER appuser

EXPOSE 8000
# No HEALTHCHECK: every backend unit runs this image and only an api serves HTTP, so a
# probe here would report a worker or a scheduler unhealthy, and `docker compose up
# --wait`, which a deploy runs, refuses a project with an unhealthy container. The profile
# probes each api unit on its declared liveness path instead (ADR 0187).
# No --reload: production serves immutable code. The server is pyproject.toml's runtime
# dependency "uvicorn[standard]", at the version uv.lock pins.
# --timeout-graceful-shutdown bounds the wait for in-flight tasks; unset, uvicorn waits
# forever, and a realtime stream never ends on its own. Eight seconds sits under Compose's
# ten-second default stop grace, so the process exits on its own terms instead of being killed.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "8"]
"""
)

_FRONTEND_DOCKERFILE = (
    HEADER
    + """#
# Production frontend image (ADR 0062). Multi-stage: stage 1 runs `vite build` over the
# exact tree frontend/package-lock.json records; stage 2 serves the static bundle from a
# non-root nginx with an SPA fallback and an /api reverse proxy to the backend, so the
# browser calls the API same-origin (no CORS).
#
# Layered so an edit to a screen rebuilds only the bundle: the manifest and the lock
# first, `npm ci` in a layer of its own, the source last. It copies nothing outside
# frontend/ but the pre-release @terpjs tarballs a checkout may vendor, so a backend edit
# never touches this image. No BuildKit cache mounts, on purpose: a release build must
# never read a cache that a development build wrote.
#
# No package's lifecycle script runs: `npm ci --ignore-scripts` installs without running
# any install hook, and the bundle is built with no network and no pre- or post-script.
# Measured on the template and the reference app, whose locks hold no package that needs
# one (ADR 0187); an app whose lock does keeps this file as its own under "build": "own".
#
"""
    + _BASE_COMMENT
    + """
# --- Stage 1: build the static bundle ------------------------------------------------
# @@NODE_TAG@@
FROM @@NODE@@ AS build

WORKDIR /app/frontend

# Only what decides the dependencies: the manifest, the lock, and the pre-release @terpjs
# tarballs a checkout vendors under .terp-dist/npm (package.json names them as
# file:../.terp-dist/npm/..., so they keep that place relative to frontend/). The
# brackets make the second COPY a pattern, so a checkout with none copies nothing.
COPY frontend/package.json frontend/package-lock.json ./
COPY .terp-dis[t]/np[m] /app/.terp-dist/npm/
# Exactly the lock: `npm ci` installs what package-lock.json records and refuses, rather
# than rewrites, a lock that disagrees with package.json ("`npm ci` can only install
# packages when your package.json and package-lock.json ... are in sync").
# `npm --prefix frontend install` is the fix, run and committed in the checkout.
RUN npm ci --ignore-scripts --no-audit --no-fund

# The source, last. .dockerignore keeps node_modules, build output and env files out.
COPY frontend/ ./
# With no network: the build reads only what `npm ci` installed and the source.
RUN --network=none npm run build --ignore-scripts

# --- Stage 2: non-root nginx runtime -------------------------------------------------
# @@NGINX_TAG@@
FROM @@NGINX@@

# The config is a TEMPLATE: the nginx entrypoint runs envsubst over /etc/nginx/templates
# at start-up. NGINX_ENVSUBST_FILTER limits substitution to API_UPSTREAM so nginx's own
# $uri / $host / $http_upgrade variables are not blanked out. The default keeps compose
# working unchanged; a co-located runtime (Azure Container Apps) overrides it.
COPY frontend/nginx.conf /etc/nginx/templates/default.conf.template
ENV API_UPSTREAM=api:8000 \\
    NGINX_ENVSUBST_FILTER=^API_UPSTREAM$
COPY --from=build /app/frontend/dist /usr/share/nginx/html

# Explicit, though `nginxinc/nginx-unprivileged` already runs as this user: the
# fact then lives in this file where a reader looks for it, and a future base
# image cannot drop it without this line failing.
USER nginx

EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=5s \\
    CMD ["/bin/sh", "-c", "wget -q -O /dev/null http://127.0.0.1:8080/"]
"""
)

_PROFILE_INTRO = """#
# The production profile (ADR 0062): the units deployment.json declares, hardened. Every
# backend unit runs with ENVIRONMENT=production, so the app refuses to boot on a weak
# SECRET_KEY, DEBUG, SQLite, permissive CORS or an insecure refresh cookie
# (terp.core.config). Secrets come from the environment only, with no development
# fallback: compose stops when a required one is unset. There is no seed service, and no
# --reload or source watch: the images are immutable. How to start it, bootstrap the
# first administrator, and point it at a database this deployment does not run:
# `terp guide deployment`.
"""

_LOGGING = """# Every service logs through this. Docker's default driver on a Synology NAS
# is `db`: one SQLite database per container, with no size cap anywhere in the
# default configuration. Appending a log line to a database that has grown to
# tens of megabytes scatters small synchronous writes across the whole file,
# which is enough to saturate a spindle on its own. A flat file that rotates
# by size costs a fraction of that, and holds the same logs.
x-logging: &container-logging
  driver: json-file
  options:
    max-size: "10m"
    max-file: "3"
"""

#: The healthcheck timing every probed service carries.
_TIMING = ("interval: 30s", "timeout: 5s", "retries: 3", "start_period: 30s")

#: The timing of a heartbeat check: every ten seconds, because the probe only reads a file
#: and a stuck loop should be reported soon after its own bound, not a minute and a half on.
_HEARTBEAT_TIMING = ("interval: 10s", "timeout: 5s", "retries: 3", "start_period: 30s")

#: The database seam when no unit of this deployment runs the database.
EXTERNAL_DATABASE_URL = "${DATABASE_URL:?DATABASE_URL is required (externalDatabase)}"
NO_DATABASE_URL = "${DATABASE_URL:?DATABASE_URL is required (no database unit)}"
KEY_SEAM = "${SECRET_KEY:?SECRET_KEY is required (>= 32 chars)}"
CORS_ORIGINS = "${BACKEND_CORS_ORIGINS:-[]}"
WEB_PORT = "${WEB_PORT:-23100}:8080"
