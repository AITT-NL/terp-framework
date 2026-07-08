"""Kernel gate for ``terp.core.secrets`` — sealed config, one decrypt call site (§5.4).

Proves the **runtime** half of the design's §5.4 control: ``mask_config`` is a
constant, oracle-free mask; ``encrypt_config`` seals into the portable
``enc:v1:`` format; and ``decrypt_config`` fails closed on every path — no
registered call site, a caller other than the registered one, a non-sealed
value, or a token that does not authenticate under the current ``SECRET_KEY``.
The matching build-time layer is the ``no_adhoc_config_decrypt`` arch rule
(tested in ``test_arch_harness.py``).
"""

from __future__ import annotations

import sys

import pytest

from terp.core import (
    SecretsError,
    decrypt_config,
    encrypt_config,
    is_sealed_config,
    mask_config,
    register_decrypt_call_site,
)
from terp.core.config import settings
from terp.core.secrets import MASKED_VALUE, reset_decrypt_call_site_runtime


@pytest.fixture(autouse=True)
def _clean_call_site():
    """Each test starts and ends with no registered decrypt call site."""
    reset_decrypt_call_site_runtime()
    yield
    reset_decrypt_call_site_runtime()


# --------------------------------------------------------------------------- #
# masking — the only module-facing view of a sealed value
# --------------------------------------------------------------------------- #


def test_mask_config_is_a_constant_oracle_free_mask() -> None:
    # The mask never varies with the value: not a prefix, not a suffix, not a length.
    assert mask_config("a") == MASKED_VALUE
    assert mask_config("a-very-long-database-password") == MASKED_VALUE
    assert mask_config("") == MASKED_VALUE


def test_is_sealed_config_detects_the_versioned_format() -> None:
    assert is_sealed_config("enc:v1:abc")
    assert not is_sealed_config("plaintext")
    assert not is_sealed_config("")


# --------------------------------------------------------------------------- #
# the §5.4 keystone: exactly one allowlisted decrypt call site
# --------------------------------------------------------------------------- #


def test_decrypt_single_call_site() -> None:
    """The design-§5.4 control: decrypt runs from the one registered site only."""
    sealed = encrypt_config("db-password")

    @register_decrypt_call_site
    def read_sealed(value: str) -> str:
        return decrypt_config(value)

    # The registered site decrypts; every other surface is refused.
    assert read_sealed(sealed) == "db-password"
    with pytest.raises(SecretsError, match="outside the registered call site"):
        decrypt_config(sealed)

    def rogue(value: str) -> str:
        return decrypt_config(value)

    with pytest.raises(SecretsError, match="outside the registered call site"):
        rogue(sealed)

    # The allowlist cannot silently grow: a second, different call site is refused...
    with pytest.raises(SecretsError, match="already registered"):
        register_decrypt_call_site(rogue)
    # ...while re-registering the same site is idempotent (a module re-import is benign).
    assert register_decrypt_call_site(read_sealed) is read_sealed


def test_decrypt_fails_closed_with_no_registered_call_site() -> None:
    sealed = encrypt_config("secret")
    with pytest.raises(SecretsError, match="no registered call site"):
        decrypt_config(sealed)


# --------------------------------------------------------------------------- #
# sealing round-trip + authenticated failure modes
# --------------------------------------------------------------------------- #


def _register_reader():
    @register_decrypt_call_site
    def read_sealed(value: str) -> str:
        return decrypt_config(value)

    return read_sealed


def test_encrypt_config_round_trips_through_the_registered_site() -> None:
    read_sealed = _register_reader()
    sealed = encrypt_config("s3cr3t-value")
    assert is_sealed_config(sealed)
    assert "s3cr3t-value" not in sealed  # sealed, not encoded
    assert read_sealed(sealed) == "s3cr3t-value"


def test_decrypt_rejects_a_value_not_in_the_sealed_format() -> None:
    read_sealed = _register_reader()
    with pytest.raises(SecretsError, match="not in the sealed"):
        read_sealed("plaintext-not-sealed")


def test_decrypt_rejects_a_token_sealed_under_a_different_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Seal under one SECRET_KEY, then rotate the key: the token no longer authenticates.
    monkeypatch.setattr(settings, "SECRET_KEY", "first-key-first-key-first-key-00")
    sealed = encrypt_config("value")
    monkeypatch.setattr(settings, "SECRET_KEY", "other-key-other-key-other-key-00")
    read_sealed = _register_reader()
    with pytest.raises(SecretsError, match="did not authenticate"):
        read_sealed(sealed)


def test_decrypt_rejects_a_tampered_token() -> None:
    read_sealed = _register_reader()
    sealed = encrypt_config("value")
    tampered = sealed[:-2] + ("AA" if not sealed.endswith("AA") else "BB")
    with pytest.raises(SecretsError, match="did not authenticate"):
        read_sealed(tampered)


# --------------------------------------------------------------------------- #
# the optional cipher extra fails closed when absent
# --------------------------------------------------------------------------- #


def test_sealing_without_the_cryptography_extra_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A None entry in sys.modules makes `from cryptography.fernet import ...` raise
    # ImportError — the "extra not installed" condition, without uninstalling anything.
    monkeypatch.setitem(sys.modules, "cryptography.fernet", None)
    with pytest.raises(SecretsError, match=r"terp-core\[secrets\]"):
        encrypt_config("value")


def test_secrets_error_is_a_typed_500_app_error() -> None:
    error = SecretsError()
    assert error.status_code == 500
    assert error.code == "secrets_error"
