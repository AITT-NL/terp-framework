"""The manifest's envelope: DSSE, with throwaway keys (ADR 0187 decision 6).

A manifest with no signature, a broken one, one by another key, and one whose payload changed
under its signature are each refused before a byte of the payload is read; Ed25519 and ECDSA
P-256 both sign; an external signer is the production path; without ``cryptography`` nothing
signs or verifies.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa

from terp.cli.release import dsse
from terp.cli.release._common import ReleaseError, canonical

PAYLOAD = canonical({"schemaVersion": 1, "inputs": {}, "outputs": {}, "collected": {}})


def pem_private(key) -> bytes:  # type: ignore[no-untyped-def]
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def pem_public(key) -> bytes:  # type: ignore[no-untyped-def]
    return key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)


@pytest.fixture(params=["ed25519", "p256"])
def key(request):  # type: ignore[no-untyped-def]
    return ed25519.Ed25519PrivateKey.generate() if request.param == "ed25519" else ec.generate_private_key(ec.SECP256R1())


def _signed(key) -> bytes:  # type: ignore[no-untyped-def]
    return canonical(dsse.envelope(PAYLOAD, [dsse.sign_with_key(key, PAYLOAD)]))


def test_pae_is_dsse_s_pre_authentication_encoding() -> None:
    assert dsse.pae("t", b"ab") == b"DSSEv1 1 t 2 ab"
    assert dsse.pae(dsse.PAYLOAD_TYPE, b"") == b"DSSEv1 45 application/vnd.terp.release-manifest.v1+json 0 "


def test_a_signed_envelope_verifies_and_its_keyid_is_the_der_sha256(key) -> None:  # type: ignore[no-untyped-def]
    public = dsse.load_public_key(pem_public(key))
    der = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    assert dsse.keyid(public) == hashlib.sha256(der).hexdigest()
    envelope = json.loads(_signed(key))
    assert envelope["payloadType"] == dsse.PAYLOAD_TYPE
    assert base64.b64decode(envelope["payload"]) == PAYLOAD
    assert dsse.verify(_signed(key), [public]) == (PAYLOAD, dsse.keyid(public))
    assert dsse.load_private_key(pem_private(key)) is not None


def test_every_way_an_envelope_can_be_wrong_is_refused(key) -> None:  # type: ignore[no-untyped-def]
    public = dsse.load_public_key(pem_public(key))
    other = dsse.load_public_key(pem_public(ed25519.Ed25519PrivateKey.generate()))
    good = json.loads(_signed(key))

    def changed(**fields) -> bytes:  # type: ignore[no-untyped-def]
        return canonical({**good, **fields})

    cases = [
        (b"not json", "is not JSON"),
        (canonical([good]), "is not a DSSE envelope"),
        (changed(extra=1), "is not a DSSE envelope"),
        (changed(payloadType="application/vnd.in-toto+json"), "not a release manifest"),
        (changed(signatures=[]), "carries no signature"),
        (changed(signatures={"a": 1}), "carries no signature"),
        (changed(payload="!!not base64!!"), "payload is not base64"),
        (changed(signatures=["x"]), r"is not \{keyid, sig\}"),
        (changed(signatures=[{"keyid": good["signatures"][0]["keyid"], "sig": "!!"}]), "signature of the envelope is not base64"),
        # a broken signature: one byte of it flipped
        (changed(signatures=[{**good["signatures"][0], "sig": base64.b64encode(bytes([base64.b64decode(good["signatures"][0]["sig"])[0] ^ 1]) + base64.b64decode(good["signatures"][0]["sig"])[1:]).decode()}]),
         "no signature of the envelope verifies"),
        # the payload changed under a valid signature
        (changed(payload=base64.b64encode(PAYLOAD.replace(b'"inputs":{}', b'"inputs":{"x":1}')).decode()), "no signature of the envelope verifies"),
        # a signature with no keyid matching
        (changed(signatures=[{"keyid": "0" * 64, "sig": good["signatures"][0]["sig"]}]), "no signature of the envelope verifies"),
        # the signed payload with a character a lenient decoder would skip: no second spelling
        (changed(payload=good["payload"][:8] + "!" + good["payload"][8:]), "payload is not base64"),
    ]
    for raw, expected in cases:
        with pytest.raises(ReleaseError, match=expected):
            dsse.verify(raw, [public])
    with pytest.raises(ReleaseError, match="signed by a key this deployment does not trust"):
        dsse.verify(_signed(key), [other])
    with pytest.raises(ReleaseError, match="no public key was given"):
        dsse.verify(_signed(key), [])


def test_another_key_kind_is_refused() -> None:
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(ReleaseError, match="neither Ed25519 nor ECDSA P-256"):
        dsse.load_public_key(pem_public(rsa_key))
    p384 = ec.generate_private_key(ec.SECP384R1())
    with pytest.raises(ReleaseError, match="neither Ed25519 nor ECDSA P-256"):
        dsse.load_private_key(pem_private(p384))
    with pytest.raises(ReleaseError, match="is not a PEM public key"):
        dsse.load_public_key(b"-----BEGIN NOTHING-----")
    with pytest.raises(ReleaseError, match="is not an unencrypted PEM private key"):
        dsse.load_private_key(b"garbage")


def test_an_external_signer_signs_with_a_key_this_process_never_holds(tmp_path, key) -> None:  # type: ignore[no-untyped-def]
    pem = tmp_path / "key.pem"
    pem.write_bytes(pem_private(key))
    script = tmp_path / "signer.py"
    script.write_text(
        "import base64, json, sys\n"
        "from cryptography.hazmat.primitives import hashes, serialization\n"
        "from cryptography.hazmat.primitives.asymmetric import ec, ed25519\n"
        "from terp.cli.release import dsse\n"
        f"key = serialization.load_pem_private_key(open({str(pem)!r}, 'rb').read(), None)\n"
        "data = sys.stdin.buffer.read()\n"
        "sig = key.sign(data) if isinstance(key, ed25519.Ed25519PrivateKey) else key.sign(data, ec.ECDSA(hashes.SHA256()))\n"
        "print(json.dumps({'keyid': dsse.keyid(key.public_key()), 'sig': base64.b64encode(sig).decode()}))\n",
        encoding="utf-8",
    )
    signature = dsse.sign_with_command([sys.executable, str(script)], PAYLOAD)
    envelope = canonical(dsse.envelope(PAYLOAD, [signature]))
    assert dsse.verify(envelope, [dsse.load_public_key(pem_public(key))])[0] == PAYLOAD
    script.write_text("print('no json')\n", encoding="utf-8")
    with pytest.raises(ReleaseError, match="did not answer"):
        dsse.sign_with_command([sys.executable, str(script)], PAYLOAD)
    script.write_text("import sys; sys.exit(3)\n", encoding="utf-8")
    with pytest.raises(ReleaseError, match=r"the signer failed \(exit 3\)"):
        dsse.sign_with_command([sys.executable, str(script)], PAYLOAD)


def test_without_cryptography_nothing_signs_or_verifies(monkeypatch, key) -> None:  # type: ignore[no-untyped-def]
    envelope = _signed(key)
    for name in ("cryptography.hazmat.primitives", "cryptography.hazmat.primitives.asymmetric"):
        monkeypatch.setitem(sys.modules, name, None)
    for call in (
        dsse.require_cryptography,
        lambda: dsse.verify(envelope, [object()]),
        lambda: dsse.load_public_key(b""),
        lambda: dsse.sign_with_key(key, PAYLOAD),
    ):
        with pytest.raises(ReleaseError, match=r"install terp-cli\[release\]"):
            call()
