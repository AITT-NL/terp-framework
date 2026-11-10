"""The ``static-site`` recipe: a static site the framework builds and serves (ADR 0198).

A ``web`` unit that ``generator.recipes`` names ``static-site`` is built from ``site/`` into
an image whose Dockerfile is this module's text, a constant of the framework release with the
base-image table's digests that takes nothing from the declaration. Stage 1 builds the site
over the exact tree ``site/package-lock.json`` records and refuses a page in whose markup it
finds what the image's policy would break in a browser; stage 2 serves ``site/dist/`` from a
non-root nginx whose server configuration this text carries too, so the policy is the recipe's
and no app can edit it.

The site proxies nothing. It is published on a variable of its own, ``WEB_PORT_`` and its unit
id upper-cased with ``-`` and ``.`` as ``_``, so every unit id the generator accepts gives a
name compose reads, and none of them is a name the profile already reads.
"""

from __future__ import annotations

import re

from terp.arch.deployment._generator_text import _BASE_COMMENT, HEADER
from terp.arch.deployment._site_check import SITE_CHECK
from terp.arch.deployment.reader import RECIPE_HEALTH_PATHS

#: The one recipe this release knows (terp-spec 0.45.0, ``generator.recipes``).
STATIC_SITE = "static-site"

#: The path the site's nginx answers itself, which the image and the profile probe, and the one
#: health path the reader lets a site unit declare: the reader's, so the two cannot differ.
SITE_HEALTH_PATH = RECIPE_HEALTH_PATHS[STATIC_SITE]

#: Where the image puts ``site/dist/`` and the server serves from: a directory only the site's
#: build fills. The base image's own ``/usr/share/nginx/html`` holds pages of its own (a
#: welcome ``index.html``, a ``50x.html`` with an inline style the policy blocks), and a
#: directory the build is copied over keeps every page the build did not overwrite.
SITE_ROOT = "/usr/share/nginx/site"

#: The host port a site takes on a first ``up`` when its variable is unset: the one after the
#: web tier's 23100. A deployment sets the variable explicitly.
SITE_PORT_DEFAULT = 23101

#: Every port scalar the generator writes for a site, for an executor's escape audit.
SITE_PORT_PATTERN = rf"\$\{{WEB_PORT_[A-Z0-9][A-Z0-9_]{{0,62}}:-{SITE_PORT_DEFAULT}\}}:8080"


def port_variable(unit: str) -> str:
    """The variable site unit *unit* is published on: ``WEB_PORT_SITE`` for unit ``site``."""
    return "WEB_PORT_" + re.sub(r"[-.]", "_", unit.upper())


def site_port(unit: str) -> str:
    """The profile's port scalar for site unit *unit*: its variable, then the default."""
    return f"${{{port_variable(unit)}:-{SITE_PORT_DEFAULT}}}:8080"


#: The site's server (decision 3): the template SPA's document headers, its content security
#: policy included, on every location that serves a file; real pages with no SPA fallback; no
#: ``/api`` location; immutable caching for ``/assets/`` and none for anything else; the site's
#: own ``404.html`` when its build writes one; and a health path nginx answers itself. It
#: serves :data:`SITE_ROOT` alone.
#:
#: ``/assets/`` repeats the document headers beside its own ``Cache-Control``. nginx drops every
#: ``add_header`` a block inherits once the block declares one, and a file under ``/assets/``
#: can be a document: an SVG opened on its own runs the script it holds. They cost nothing on a
#: script or a stylesheet.
#:
#: It names no nginx version (``server_tokens off``), and it listens on IPv4 alone, as the
#: template SPA's ``frontend/nginx.conf`` now does too: on a host whose kernel has no IPv6, a
#: ``[::]`` listen stops nginx at start. An app can edit its SPA's file, and nobody can edit
#: this one, so it must start on every host. A port compose publishes reaches the container
#: over the network's IPv4 address, which the generated profile never gives an IPv6 one.
SITE_NGINX = """server {
    # IPv4 alone: a [::] listen stops nginx on a host whose kernel has no IPv6.
    listen 8080;
    server_name _;
    # No nginx version in a Server header or on an error page nginx writes.
    server_tokens off;

    # site/dist/ and nothing else: the base image's own pages stay out of the root.
    root /usr/share/nginx/site;
    index index.html;

    gzip on;
    gzip_types text/css application/javascript application/json image/svg+xml;

    location = /healthz {
        access_log off;
        default_type text/plain;
        return 200 "ok\\n";
    }

    # Content-hashed assets are immutable: the site's build writes them under /assets/. The
    # document headers again, since this block's own add_header drops every inherited one,
    # and an asset can be a document: an SVG opened on its own runs the script it holds.
    location /assets/ {
        add_header Cache-Control "public, max-age=31536000, immutable";
        add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "no-referrer" always;
        add_header Cross-Origin-Opener-Policy "same-origin" always;
        add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;
        try_files $uri =404;
    }

    # Real pages: a path is a file, or a directory with an index.html, or the site's 404.
    location / {
        add_header Cache-Control "no-cache";
        add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "no-referrer" always;
        add_header Cross-Origin-Opener-Policy "same-origin" always;
        add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;
        try_files $uri $uri/index.html =404;
    }

    error_page 404 /404.html;
}
"""

_SITE_DOCKERFILE = (
    HEADER
    + """#
# Static site image (ADR 0198): the static-site recipe. Stage 1 builds site/ over the exact
# tree site/package-lock.json records, with no build argument, no secret and none of the
# app's environment, and refuses a page in whose markup it finds what the policy below would
# break in a browser. Stage 2 serves site/dist/ from a non-root nginx whose server
# configuration this file carries: the site proxies nothing, so a page reaches nothing of the
# app, and the policy is the recipe's.
#
# No package's lifecycle script runs: `npm ci --ignore-scripts` installs without running any
# install hook, and the site is built with no network and no pre- or post-script. A site that
# needs a lifecycle script, another policy or the app's environment keeps this file as its
# own under "build": "own".
#
"""
    + _BASE_COMMENT
    + """
# --- Stage 1: build the site ------------------------------------------------------------
# @@NODE_TAG@@
FROM @@NODE@@ AS build

WORKDIR /app/site

# Only what decides the dependencies, then exactly the lock: `npm ci` refuses, rather than
# rewrites, a lock that disagrees with package.json.
COPY site/package.json site/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund

# The source, last. .dockerignore keeps node_modules, build output and env files out.
COPY site/ ./
# With no network: the build reads only what `npm ci` installed and the source.
RUN --network=none npm run build --ignore-scripts

# The policy refuses inline script and style, a script, stylesheet, frame, image or media
# from another origin, and more in the browser, where a page that breaks leaves nothing in
# any log. This looks for those in each page's markup first and refuses the build where it
# finds one, naming the file, its first such tag and what to change. The policy is the
# control: the check finds what it can see before the image is made, and a pass is no promise.
COPY <<"TERP_SITE_CHECK" /usr/local/lib/terp-site-check.mjs
"""
    + SITE_CHECK
    + """TERP_SITE_CHECK
RUN --network=none node /usr/local/lib/terp-site-check.mjs dist

# --- Stage 2: non-root nginx runtime -------------------------------------------------------
# @@NGINX_TAG@@
FROM @@NGINX@@

COPY <<"TERP_SITE_NGINX" /etc/nginx/conf.d/default.conf
"""
    + SITE_NGINX
    + """TERP_SITE_NGINX
# Into a directory of its own, which the server configuration above names as its root, and
# never over the base image's html directory, whose own pages a copy would leave in place.
COPY --from=build /app/site/dist /usr/share/nginx/site

# Explicit, though `nginxinc/nginx-unprivileged` already runs as this user: the fact then
# lives in this file where a reader looks for it, and a future base image cannot drop it
# without this line failing.
USER nginx

EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=5s \\
    CMD ["/bin/sh", "-c", "wget -q -O /dev/null http://127.0.0.1:8080/healthz"]
"""
)
