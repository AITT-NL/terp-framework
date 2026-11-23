"""The conformance suite's image: the app's own suite, built for a runner to run (ADR 0219).

The suite is the Playwright tests of an app's ``conformance/`` directory, on the framework's
``@terpjs/conformance`` helpers, which ``terp verify --profile release`` already runs in the
release's CI. A release also builds it into an image of its own, which no unit runs: a runner's
verify step starts it against a disposable stack of the release's exact digests and reads its
exit (terp-runner's design, section 11.35). The image's Dockerfile is this module's text, a
constant of the framework release with the base-image table's digest that takes nothing from the
declaration, rendered where the checkout commits the suite's lock.

What the suite is given, and how it runs, is the release's to record (``outputs.suite``): the
command below, and the names of the three variables the suite reads. The runner gives the target
unit's address and a throwaway administrator under those names, and nothing else.
"""

from __future__ import annotations

from terp.arch.deployment._generator_text import (
    _BASE_COMMENT,
    HEADER,
    SUITE_DOCKERFILE,
    SUITE_LOCK,
)

#: Where the image holds the suite, and runs it from.
SUITE_ROOT = "/suite"

#: What the image runs: the suite's own Playwright, from the suite's root, with nothing before
#: it. The manifest records it as ``outputs.suite.command``, and the runner gives it unchanged.
SUITE_COMMAND = (f"{SUITE_ROOT}/node_modules/.bin/playwright", "test")

#: The names of what the suite reads, as ``@terpjs/conformance`` and the template's suite read
#: them: the address of the unit it drives, and the administrator it signs in as.
SUITE_READS = {
    "address": "TERP_E2E_BASE_URL",
    "email": "TERP_E2E_ADMIN_EMAIL",
    "password": "TERP_E2E_ADMIN_PASSWORD",
}


def suite_image(project: str) -> str:
    """The name of the suite's image for *project*, as the generator names the release's others."""
    return f"{project}-conformance-prod"


_SUITE_DOCKERFILE = (
    HEADER
    + """#
# Conformance suite image (ADR 0219): the Playwright tests of conformance/, which the release
# gate runs in CI, built into an image no unit runs. A runner's verify step starts it against
# a disposable stack of the release's exact digests, on a network with no route out, gives it
# the address of the unit it drives and a throwaway administrator, and reads its exit.
#
# The base is Playwright's own image, which holds the browsers of one Playwright release and
# no other. The build refuses a lock whose @playwright/test is another release: its browsers
# would not be in the image, and the suite would fail on what it cannot launch, not on the app.
#
# Layered as the frontend's is: the manifest and the lock first, `npm ci` in a layer of its
# own, the suite last. No package's lifecycle script runs (`npm ci --ignore-scripts`), and the
# suite runs as the image's own unprivileged user, which owns the directory it writes its
# results to.
#
"""
    + _BASE_COMMENT
    + """
# @@PLAYWRIGHT_TAG@@
FROM @@PLAYWRIGHT@@

# The pre-release @terpjs tarballs a checkout vendors under .terp-dist/npm, where
# package.json names them as file:../.terp-dist/npm/...; the brackets make it a pattern, so a
# checkout with none copies nothing.
COPY .terp-dis[t]/np[m] /.terp-dist/npm/

WORKDIR @@SUITE_ROOT@@
RUN chown pwuser:pwuser @@SUITE_ROOT@@
USER pwuser

COPY --chown=pwuser:pwuser conformance/package.json conformance/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund

# The suite's own Playwright must be the one whose browsers the base holds.
RUN found="$(node -p 'require("./node_modules/@playwright/test/package.json").version')" \\
 && if [ "$found" != "@@PLAYWRIGHT_VERSION@@" ]; then \\
      echo "conformance/package-lock.json pins @playwright/test $found, and this image holds the browsers of Playwright @@PLAYWRIGHT_VERSION@@: pin @playwright/test @@PLAYWRIGHT_VERSION@@ in conformance/ (npm --prefix conformance install @playwright/test@@@PLAYWRIGHT_VERSION@@), or move to a framework release whose base is $found" >&2; \\
      exit 1; \\
    fi

# The suite, last. .dockerignore keeps node_modules and results out.
COPY --chown=pwuser:pwuser conformance/ ./

ENV CI=1
CMD @@SUITE_COMMAND@@
"""
)


def suite_dockerfile(base: str, tag: str, version: str) -> str:
    """The suite's Dockerfile on the Playwright *base* read from *tag*, for its *version*."""
    return (
        _SUITE_DOCKERFILE.replace("@@PLAYWRIGHT_TAG@@", tag)
        .replace("@@PLAYWRIGHT_VERSION@@", version)
        .replace("@@PLAYWRIGHT@@", base)
        .replace("@@SUITE_ROOT@@", SUITE_ROOT)
        .replace("@@SUITE_COMMAND@@", "[" + ", ".join(f'"{part}"' for part in SUITE_COMMAND) + "]")
    )


__all__ = [
    "SUITE_COMMAND",
    "SUITE_DOCKERFILE",
    "SUITE_LOCK",
    "SUITE_READS",
    "SUITE_ROOT",
    "suite_dockerfile",
    "suite_image",
]
