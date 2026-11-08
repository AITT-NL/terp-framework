"""The ``static-site`` recipe: a static site the framework builds and serves (ADR 0198).

A ``web`` unit that ``generator.recipes`` names ``static-site`` is built from ``site/`` into
an image whose Dockerfile is this module's text, a constant of the framework release with the
base-image table's digests that takes nothing from the declaration. Stage 1 builds the site
over the exact tree ``site/package-lock.json`` records and refuses a page the image's policy
would break in a browser; stage 2 serves ``site/dist/`` from a non-root nginx whose server
configuration this text carries too, so the policy is the recipe's and no app can edit it.

The site proxies nothing. It is published on a variable of its own, ``WEB_PORT_`` and its unit
id upper-cased with ``-`` and ``.`` as ``_``, so every unit id the generator accepts gives a
name compose reads, and none of them is a name the profile already reads.
"""

from __future__ import annotations

import re

from terp.arch.deployment._generator_text import _BASE_COMMENT, HEADER

#: The one recipe this release knows (terp-spec 0.45.0, ``generator.recipes``).
STATIC_SITE = "static-site"

#: The path the site's nginx answers itself, which the image and the profile probe.
SITE_HEALTH_PATH = "/healthz"

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


#: The refusal at build (decision 2): an HTML file under ``dist/`` with an inline script that
#: runs, a ``<style>`` element, a ``style`` attribute, an event-handler attribute or a
#: ``javascript:`` URL, each of which the policy below refuses in a browser. Any attribute
#: named ``on`` and letters is read as an event handler, which every handler HTML defines is;
#: a page's own attribute takes a ``data-`` name. A data block such as JSON-LD runs as
#: nothing and passes, and so does markup a browser reads as text or as a comment.
SITE_CHECK = r"""import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const RUNS = new Set([
  "", "module", "importmap", "speculationrules", "application/ecmascript",
  "application/javascript", "application/x-ecmascript", "application/x-javascript",
  "text/ecmascript", "text/javascript", "text/javascript1.0", "text/javascript1.1",
  "text/javascript1.2", "text/javascript1.3", "text/javascript1.4", "text/javascript1.5",
  "text/jscript", "text/livescript", "text/x-ecmascript", "text/x-javascript",
]);
const RAW = new Set([
  "iframe", "noembed", "noframes", "noscript", "plaintext", "script", "style", "textarea",
  "title", "xmp",
]);
const URLS = new Set(["action", "formaction", "href", "src", "xlink:href"]);
const SPACE = /[\t\n\f\r ]/;

function readTag(html, at) {
  const attrs = [];
  let name = "";
  let value = "";
  let state = "between";
  const flush = () => {
    if (name) attrs.push([name.toLowerCase(), value]);
    name = "";
    value = "";
  };
  for (let i = at; i < html.length; i += 1) {
    const c = html[i];
    if (state === "dq" || state === "sq") {
      if (c === (state === "dq" ? '"' : "'")) {
        flush();
        state = "between";
      } else value += c;
    } else if (state === "unquoted") {
      if (SPACE.test(c)) {
        flush();
        state = "between";
      } else if (c === ">") {
        flush();
        return [attrs, i];
      } else value += c;
    } else if (state === "before") {
      if (c === '"') state = "dq";
      else if (c === "'") state = "sq";
      else if (c === ">") {
        flush();
        return [attrs, i];
      } else if (!SPACE.test(c)) {
        value = c;
        state = "unquoted";
      }
    } else if (c === ">") {
      flush();
      return [attrs, i];
    } else if (c === "=" && state !== "between") state = "before";
    else if (SPACE.test(c) || c === "/") {
      if (state === "name") state = "after";
    } else if (state === "name") name += c;
    else {
      flush();
      name = c;
      state = "name";
    }
  }
  flush();
  return [attrs, html.length];
}

function offense(name, attrs, content) {
  const named = new Map(attrs);
  if (name === "script" && !named.has("src") && content.trim()) {
    const type = (named.get("type") ?? "").split(";")[0].trim().toLowerCase();
    if (RUNS.has(type)) return "is an inline script";
  }
  if (name === "style" && content.trim()) return "is a <style> element";
  for (const [attribute, written] of attrs) {
    if (attribute === "style" && written.trim()) return "carries a style attribute";
    if (/^on[a-z]+$/.test(attribute) && written.trim()) return `carries the event handler ${attribute}`;
    const url = written.replace(/[\u0000- ]/g, "").toLowerCase();
    if (URLS.has(attribute) && url.startsWith("javascript:")) return `points ${attribute} at javascript:`;
  }
  return null;
}

export function firstOffense(html) {
  let at = 0;
  while ((at = html.indexOf("<", at)) !== -1) {
    if (html.startsWith("<!--", at)) {
      const end = html.indexOf("-->", at + 4);
      at = end === -1 ? html.length : end + 3;
      continue;
    }
    const head = /^<(\/?)([A-Za-z][^\t\n\f\r />]*)/.exec(html.slice(at, at + 256));
    if (head === null) {
      // A doctype, a CDATA section or a processing instruction runs to its first ">";
      // any other "<" is text.
      const markup = html[at + 1] === "!" || html[at + 1] === "?";
      const end = markup ? html.indexOf(">", at) : -1;
      at = markup ? (end === -1 ? html.length : end + 1) : at + 1;
      continue;
    }
    const [attrs, end] = readTag(html, at + head[0].length);
    const name = head[2].toLowerCase();
    const tag = html.slice(at, end + 1);
    at = end + 1;
    if (head[1]) continue;
    let content = "";
    if (RAW.has(name)) {
      const close = new RegExp(`</${name}(?=[\\t\\n\\f\\r />])`, "i").exec(html.slice(at));
      content = close === null ? html.slice(at) : html.slice(at, at + close.index);
      at = close === null ? html.length : at + close.index;
    }
    const why = offense(name, attrs, content);
    if (why !== null) return `${tag.length > 120 ? `${tag.slice(0, 117)}...` : tag} ${why}`;
  }
  return null;
}

function pages(dir) {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return pages(path);
    return /\.html?$/i.test(entry) ? [path] : [];
  });
}

if (process.argv[2] !== undefined) {
  const refused = pages(process.argv[2]).flatMap((page) => {
    const why = firstOffense(readFileSync(page, "utf8"));
    return why === null ? [] : [`site/${relative(".", page)}: ${why}`];
  });
  for (const line of refused) console.error(line);
  if (refused.length) {
    console.error(
      "The site's policy refuses inline script and style in the browser (terp-framework ADR " +
        "0198): write each as a file the page loads, or build the site under \"build\": \"own\".",
    );
    process.exit(1);
  }
}
"""

#: The site's server (decision 3): the template SPA's document headers, its content security
#: policy included; real pages with no SPA fallback; no ``/api`` location; immutable caching
#: for ``/assets/`` and none for anything else; the site's own ``404.html`` when its build
#: writes one; and a health path nginx answers itself.
SITE_NGINX = """server {
    listen 8080;
    listen [::]:8080;
    server_name _;

    root /usr/share/nginx/html;
    index index.html;

    gzip on;
    gzip_types text/css application/javascript application/json image/svg+xml;

    location = /healthz {
        access_log off;
        default_type text/plain;
        return 200 "ok\\n";
    }

    # Content-hashed assets are immutable: the site's build writes them under /assets/.
    location /assets/ {
        add_header Cache-Control "public, max-age=31536000, immutable";
        add_header X-Content-Type-Options "nosniff" always;
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
# app's environment, and refuses a page the policy below would break in a browser. Stage 2
# serves site/dist/ from a non-root nginx whose server configuration this file carries: the
# site proxies nothing, so a page reaches nothing of the app, and the policy is the recipe's.
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

# The policy refuses inline script and style in the browser, where a page that breaks leaves
# nothing in any log, so the build refuses them first, naming each file and its first tag.
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
COPY --from=build /app/site/dist /usr/share/nginx/html

# Explicit, though `nginxinc/nginx-unprivileged` already runs as this user: the fact then
# lives in this file where a reader looks for it, and a future base image cannot drop it
# without this line failing.
USER nginx

EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=5s \\
    CMD ["/bin/sh", "-c", "wget -q -O /dev/null http://127.0.0.1:8080/healthz"]
"""
)
