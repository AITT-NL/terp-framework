"""Suite-wide isolation for the CLI's machine-scoped state.

``terp ports`` keeps its ledger in ``~/.terp/ports.json``, because the resource it
allocates — a host port — belongs to the machine rather than to any checkout. That
is the right home for it and a hazard for a test suite by construction: anything
that reaches the command writes a developer's own file, and the damage is quiet.
It was found the ordinary way. Wiring assignment into ``terp docker dev`` made
five tests in ``test_cli_docker.py`` — written long before the command existed and
naming nothing about ports — deposit eleven claims in a real ledger, one of them
for this very checkout.

So the isolation is autouse and lives here rather than in the file that noticed.
A test that has to remember to opt in is a test the next author forgets to write,
and the next author has no reason to suspect that starting a fake compose stack
touches their home directory.

Not in the repo-root ``conftest.py`` on purpose: that file's whole argument is that
process-global *runtime* isolation ships with the platform (``terp.core.testing``)
so an app receives it the same way this repo does, and a hand-maintained fixture
beside it would be the thing it says it deleted. This is a different concern — the
CLI's own state on the developer's machine — and its scope is the suite that can
reach it.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_terp_home(tmp_path_factory, monkeypatch):
    """Point ``TERP_HOME`` at a per-test directory for every test in this suite.

    Per test rather than per session: two tests sharing a ledger would make the
    pair order-dependent, and a port claimed by an earlier test would narrow what
    a later one is handed — the class of coupling this suite is otherwise careful
    not to have.
    """
    monkeypatch.setenv("TERP_HOME", str(tmp_path_factory.mktemp("terp-home")))
