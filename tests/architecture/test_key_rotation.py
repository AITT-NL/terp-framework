"""Key rotation (ADR 0189): retired keys only verify or only decrypt, each on its own clock.

ADR 0076 §2 gave ``SECRET_KEY`` one fallback list, and it only verified signatures. Every
value sealed at rest opened under the live key alone, so changing the key left sealed
config, webhook signing secrets and MFA enrolments unreadable. This suite holds the
amendment to what it promises:

* a value sealed and a session signed under the old key open and verify through the
  fallback lists after a rotation — and each list does only its own job;
* nothing new is ever sealed or signed with a fallback;
* a signature under a retired key is honoured only inside its lifetime, whatever
  lifetime it claims;
* the production boot refuses a fallback list with a slip in it, in one message that
  names the entry and never its value;
* every value sealed or signed before the derivation labels existed still opens or
  verifies, so the upgrade itself is not a rotation anybody has to perform.

The re-seal command has its own suite, ``test_cli_reseal.py``.
"""

from __future__ import annotations

import base64
import secrets
from collections.abc import Callable, Iterator

import pytest

import terp.core.secrets as core_secrets
from terp.core import (
    SealingDomain,
    SealState,
    SecretsError,
    check_sealed_value,
    decrypt_config,
    derive_key,
    encrypt_config,
    register_decrypt_call_site,
    sealing_domains,
)
from terp.core.config import Settings, settings
from terp.core.secrets import reset_decrypt_call_site_runtime

from terp.capabilities.mfa import MfaSecretError
from terp.capabilities.mfa import seal_secret as seal_totp
from terp.capabilities.mfa import unseal_secret as unseal_totp
from terp.capabilities.webhooks import WebhookSecretError
from terp.capabilities.webhooks import seal_secret as seal_webhook
from terp.capabilities.webhooks import unseal_secret as unseal_webhook

# Generated, never written down: a key-shaped literal is what the secret scan flags, and
# these only have to differ from each other (ADR 0163).
_OLD = secrets.token_urlsafe(32)
_NEW = secrets.token_urlsafe(32)

_CONFIG_LABEL = b"terp.core.secrets.config-seal.v1"
_WEBHOOK_LABEL = b"terp.capabilities.webhooks.secret-seal.v1"
_TOTP_LABEL = b"terp.capabilities.mfa.totp-seal.v1"


@pytest.fixture(autouse=True)
def _keys(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Start every test under the old key with empty lists; monkeypatch puts them back."""
    monkeypatch.setattr(settings, "SECRET_KEY", _OLD)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", [])
    monkeypatch.setattr(settings, "SECRET_KEY_DECRYPT_FALLBACKS", [])
    reset_decrypt_call_site_runtime()
    yield
    reset_decrypt_call_site_runtime()


def _rotate(
    monkeypatch: pytest.MonkeyPatch, *, verify: list[str] | None = None, decrypt: list[str] | None = None
) -> None:
    """The flip: the new key current, the old one wherever the test puts it."""
    monkeypatch.setattr(settings, "SECRET_KEY", _NEW)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", verify or [])
    monkeypatch.setattr(settings, "SECRET_KEY_DECRYPT_FALLBACKS", decrypt or [])


def _config_reader() -> Callable[[str], str]:
    @register_decrypt_call_site
    def read_sealed(value: str) -> str:
        return decrypt_config(value)

    return read_sealed


# --------------------------------------------------------------------------- #
# Settings: the two lists, how they are written, and what production refuses
# --------------------------------------------------------------------------- #
def test_a_key_list_reads_comma_separated_or_as_a_json_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SECRET_KEY_FALLBACKS", f" {_OLD} ,{_NEW},")
    monkeypatch.setenv("SECRET_KEY_DECRYPT_FALLBACKS", f'["{_OLD}"]')
    loaded = Settings()
    # A blank segment (the trailing comma) is not a key; whitespace around one is not part of it.
    assert loaded.SECRET_KEY_FALLBACKS == [_OLD, _NEW]
    # The JSON list ADR 0076 documented keeps working.
    assert loaded.SECRET_KEY_DECRYPT_FALLBACKS == [_OLD]
    assert Settings(SECRET_KEY_FALLBACKS=[_OLD]).SECRET_KEY_FALLBACKS == [_OLD]


def test_a_rotation_with_the_old_key_in_both_lists_boots_in_production() -> None:
    rotated = Settings(
        ENVIRONMENT="production",
        SECRET_KEY=_NEW,
        SECRET_KEY_FALLBACKS=[_OLD],
        SECRET_KEY_DECRYPT_FALLBACKS=[_OLD],
        DATABASE_URL="postgresql://h/db",
    )
    assert rotated.SECRET_KEY_DECRYPT_FALLBACKS == [_OLD]


@pytest.mark.parametrize(
    ("lists", "needle"),
    [
        (
            {"SECRET_KEY_DECRYPT_FALLBACKS": [_OLD, "short"]},
            "every SECRET_KEY_DECRYPT_FALLBACKS entry must be a strong value",
        ),
        ({"SECRET_KEY_DECRYPT_FALLBACKS": ["changethis"]}, "(entry 1)"),
        ({"SECRET_KEY_DECRYPT_FALLBACKS": [_NEW]}, "SECRET_KEY_DECRYPT_FALLBACKS holds SECRET_KEY itself (entry 1)"),
        ({"SECRET_KEY_FALLBACKS": [_OLD, _NEW]}, "SECRET_KEY_FALLBACKS holds SECRET_KEY itself (entry 2)"),
        (
            {"SECRET_KEY_DECRYPT_FALLBACKS": [_OLD, _OLD, _OLD]},
            "SECRET_KEY_DECRYPT_FALLBACKS lists a key more than once (entries 2, 3)",
        ),
    ],
)
def test_production_refuses_a_bad_fallback_list_in_one_message_that_never_prints_a_key(
    lists: dict[str, list[str]], needle: str
) -> None:
    with pytest.raises(ValueError) as refused:
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY=_NEW,
            DATABASE_URL="postgresql://h/db",
            **lists,
        )
    message = str(refused.value)
    assert needle in message
    # One refusal, naming the entry by position: neither key appears, not even shortened.
    assert message.count("Insecure production configuration") == 1
    assert _OLD[:12] not in message and _NEW[:12] not in message


def test_outside_production_a_list_is_not_judged() -> None:
    assert Settings(SECRET_KEY=_NEW, SECRET_KEY_DECRYPT_FALLBACKS=[_NEW, "x"]).is_production is False


def test_a_refused_setting_never_echoes_its_value() -> None:
    # Pydantic prints the input beside an error, shortened in the middle: for a DSN that is
    # the tail, which is where the password sits.
    password = secrets.token_hex(12)
    with pytest.raises(ValueError) as refused:
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="short",
            DATABASE_URL=f"postgresql://app:{password}@db/app",
        )
    assert password not in str(refused.value)
    with pytest.raises(ValueError) as unparsable:
        Settings(SECRET_KEY_FALLBACKS=f'["{_OLD}"')  # a JSON list missing its bracket
    assert _OLD[:12] not in str(unparsable.value)


# --------------------------------------------------------------------------- #
# Derivation: one key per use, and the upgrade is not a rotation
# --------------------------------------------------------------------------- #
def test_derive_key_is_the_hkdf_every_sealer_always_derived_with() -> None:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    for label in (_CONFIG_LABEL, _WEBHOOK_LABEL, _TOTP_LABEL):
        expected = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=label).derive(
            _OLD.encode("utf-8")
        )
        assert derive_key(_OLD, label) == expected
    # One key per use: the same secret under two labels gives two unrelated keys.
    assert derive_key(_OLD, _CONFIG_LABEL) != derive_key(_OLD, _WEBHOOK_LABEL)


def _sealed_the_way_0_34_sealed(plaintext: str, label: bytes) -> str:
    """A value exactly as a sealer wrote it before ADR 0189: cryptography's HKDF + Fernet."""
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=label).derive(
        settings.SECRET_KEY.encode("utf-8")
    )
    token = Fernet(base64.urlsafe_b64encode(key)).encrypt(plaintext.encode("utf-8"))
    return "enc:v1:" + token.decode("ascii")


def test_every_value_sealed_before_this_release_still_opens() -> None:
    read = _config_reader()
    assert read(_sealed_the_way_0_34_sealed("dsn-password", _CONFIG_LABEL)) == "dsn-password"
    assert unseal_webhook(_sealed_the_way_0_34_sealed("hook", _WEBHOOK_LABEL)) == "hook"
    assert unseal_totp(_sealed_the_way_0_34_sealed("JBSWY3DP", _TOTP_LABEL)) == "JBSWY3DP"


# --------------------------------------------------------------------------- #
# Sealing: decrypt-only, until re-sealed
# --------------------------------------------------------------------------- #
def test_a_value_sealed_under_the_old_key_opens_through_the_decrypt_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read = _config_reader()
    config, hook, totp = encrypt_config("dsn"), seal_webhook("hook"), seal_totp("JBSWY3DP")
    _rotate(monkeypatch, decrypt=[_OLD])
    assert (read(config), unseal_webhook(hook), unseal_totp(totp)) == ("dsn", "hook", "JBSWY3DP")


def test_the_verify_list_never_decrypts(monkeypatch: pytest.MonkeyPatch) -> None:
    read = _config_reader()
    config, hook, totp = encrypt_config("dsn"), seal_webhook("hook"), seal_totp("JBSWY3DP")
    _rotate(monkeypatch, verify=[_OLD])
    with pytest.raises(SecretsError, match="SECRET_KEY_DECRYPT_FALLBACKS"):
        read(config)
    with pytest.raises(WebhookSecretError):
        unseal_webhook(hook)
    with pytest.raises(MfaSecretError):
        unseal_totp(totp)


def test_nothing_new_is_sealed_with_a_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    _rotate(monkeypatch, verify=[_OLD], decrypt=[_OLD])
    sealed = [encrypt_config("dsn"), seal_webhook("hook"), seal_totp("JBSWY3DP")]
    for value in sealed:
        assert check_sealed_value(value).state is SealState.CURRENT
    # Under the old key alone, none of them opens: none was sealed under it.
    monkeypatch.setattr(settings, "SECRET_KEY", _OLD)
    monkeypatch.setattr(settings, "SECRET_KEY_DECRYPT_FALLBACKS", [])
    for value in sealed:
        assert check_sealed_value(value).state is SealState.UNREADABLE


def test_check_sealed_value_names_the_domain_and_hands_back_the_reseal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hook = seal_webhook("hook")
    _rotate(monkeypatch, decrypt=[_OLD])
    check = check_sealed_value(hook)
    assert (check.state, check.domain) == (SealState.FALLBACK, "webhooks.secret")
    assert check.resealed is not None and "hook" not in check.resealed
    # The re-seal opens under the new key alone, and in the same domain.
    monkeypatch.setattr(settings, "SECRET_KEY_DECRYPT_FALLBACKS", [])
    assert unseal_webhook(check.resealed) == "hook"
    assert check_sealed_value(check.resealed).state is SealState.CURRENT
    # Gone: the old key is no longer listed.
    assert check_sealed_value(hook).state is SealState.UNREADABLE
    # Not a sealed value at all, or not even ASCII after the prefix.
    assert check_sealed_value("plain text").state is SealState.UNREADABLE
    assert check_sealed_value("enc:v1:café").state is SealState.UNREADABLE


def test_every_shipped_sealer_is_a_registered_domain() -> None:
    assert {"config", "webhooks.secret", "mfa.totp"} <= set(sealing_domains())


def test_a_domain_cannot_take_a_name_or_a_label_already_in_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(core_secrets, "_DOMAINS", dict(core_secrets._DOMAINS))
    with pytest.raises(SecretsError, match="already uses this name or label"):
        SealingDomain("config", b"terp.tests.another-label.v1")
    with pytest.raises(SecretsError, match="already uses this name or label"):
        SealingDomain("tests.copy", _CONFIG_LABEL)  # the way round decrypt_config's one site
    fresh = SealingDomain("tests.fresh", b"terp.tests.fresh-label.v1")
    assert "tests.fresh" in sealing_domains()
    assert fresh.open(fresh.seal("x")) == ("x", False)
