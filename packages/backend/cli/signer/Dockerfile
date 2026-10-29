# The signer image: the operator's own toolchain for `terp release sign` (ADR 0187 decision 6).
#
# `sign` never runs at the version a release pins, so an app cannot choose its own verifier: it
# runs from this image, at the framework's newest release. The image holds terp-cli with its
# `release` extra, installed from a hash-locked requirements file and the framework's own wheels
# (tools/signer_context.py writes both), gitleaks for the secret scan, the docker client the
# bytecode check runs the base image's interpreter with (never an app image), git to read the
# commit, and the terp-arch release table: the wheel SHA-256 of every terp-arch release from the
# floor up, the only wheels `sign` renders with.
#
# The framework's CI builds it from the commit's wheels and runs it; nothing publishes it yet.
# What the release pipeline will add, and the reason each is not here: publishing it by digest
# with provenance, so an operator pins the image rather than a tag; the release table filled
# from the published terp-arch wheels' hashes, which exist only once a release is on the index
# (this table is empty until then, so this build signs nothing a published app pins); and git
# from a pinned source, as the bases are, where apt installs Debian's current one today.
#
# Built as: docker build --pull --no-cache -f Dockerfile <context>, the context holding this
# file, requirements.txt, wheels/ and terp-arch-releases.json.
#
# Run with the checkout mounted read-only and the engine the bytecode check starts the base
# interpreter on: its socket mounted, and the socket's group added (`--group-add`), because the
# image runs as its own user, `signer`, who owns neither (a checkout another user owns is read
# all the same: sign tells git the named repository is safe). A registry on the loopback, the
# release lane's, is reached with `--network host`. The release lane runs it exactly so
# (tests/release_lane/).

# python:3.14-slim, the base-image table's interpreter (terp-arch's base-images.json).
FROM python@sha256:fbecd461fc72d21b2143c6eaba25143738079154a6d0ea3da3aec724f50eed4a AS install
COPY wheels/ /wheels/
COPY requirements.txt /requirements.txt
# Every distribution by its hash: the third-party ones as uv.lock pins them, the framework's as
# built for this image, each named by its file under /wheels and never by its version, which an
# index may carry too (between two releases the tree's is the last published one, and pip took
# that wheel). --no-deps: the file names every one, so nothing is resolved here.
RUN python -m venv /opt/terp \
    && /opt/terp/bin/pip install --no-cache-dir --no-deps --require-hashes -r /requirements.txt

# gitleaks v8.30.1, by digest (zricethezav/gitleaks:v8.30.1, read 2026-10-22).
FROM zricethezav/gitleaks@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f AS gitleaks
# The docker client 29.9.2, by digest (docker:29.9.2-cli, read 2026-10-22).
FROM docker@sha256:5e6baf67325a79f64ed3bed6863954d5e05d0f3d4e57cbdb14809346814bbfdb AS docker

FROM python@sha256:fbecd461fc72d21b2143c6eaba25143738079154a6d0ea3da3aec724f50eed4a
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 signer
COPY --from=gitleaks /usr/bin/gitleaks /usr/local/bin/gitleaks
COPY --from=docker /usr/local/bin/docker /usr/local/bin/docker
COPY --from=install /opt/terp /opt/terp
COPY terp-arch-releases.json /etc/terp/terp-arch-releases.json
ENV PATH="/opt/terp/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1
USER signer
ENTRYPOINT ["terp", "release"]
CMD ["sign", "--help"]
