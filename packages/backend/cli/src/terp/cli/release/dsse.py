"""The release manifest's envelope: DSSE, signed over its pre-authentication encoding.

ADR 0187 decision 6. The manifest's bytes are the envelope's payload, base64-encoded, under the
payload type ``application/vnd.terp.release-manifest.v1+json``; each signature is over DSSE's
pre-authentication encoding of the type and the bytes (``PAE``), so a signature over a manifest
can never be read as one over anything else, and the payload is verified before it is parsed.
A signature's ``keyid`` is the hexadecimal SHA-256 of its public key's DER
``SubjectPublicKeyInfo``. Ed25519 and ECDSA P-256 (with SHA-256) are the two key kinds.

``cryptography`` is the optional extra ``terp-cli[release]``. Without it nothing here runs:
signing and verifying refuse, by name, and no verification is ever skipped.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Sequence
from typing import Any

from terp.cli.release._common import ReleaseError, require, run

PAYLOAD_TYPE = "application/vnd.terp.release-manifest.v1+json"


def pae(payload_type: str, payload: bytes) -> bytes:
    """DSSE's pre-authentication encoding of *payload* under *payload_type*."""
    kind = payload_type.encode("utf-8")
    return b"DSSEv1 %d %s %d %s" % (len(kind), kind, len(payload), payload)


def _cryptography() -> Any:
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec, ed25519
    except ImportError as exc:
        raise ReleaseError(
            "signing and verifying a release need cryptography: install terp-cli[release]. "
            "Nothing is signed or deployed without it, and no verification is skipped."
        ) from exc

    class Crypto:
        pass

    crypto = Crypto()
    crypto.hashes, crypto.serialization, crypto.ec, crypto.ed25519 = hashes, serialization, ec, ed25519
    return crypto


def require_cryptography() -> None:
    """Refuse up front, before any work, where ``cryptography`` is missing."""
    _cryptography()


def _kind(key: Any, crypto: Any) -> str:
    if isinstance(key, (crypto.ed25519.Ed25519PublicKey, crypto.ed25519.Ed25519PrivateKey)):
        return "ed25519"
    if isinstance(key, (crypto.ec.EllipticCurvePublicKey, crypto.ec.EllipticCurvePrivateKey)) and isinstance(
        key.curve, crypto.ec.SECP256R1
    ):
        return "p256"
    raise ReleaseError("the key is neither Ed25519 nor ECDSA P-256, the two a release is signed with")


def load_public_key(pem: bytes) -> Any:
    """A PEM public key of a kind a release is signed with."""
    crypto = _cryptography()
    try:
        key = crypto.serialization.load_pem_public_key(pem)
    except ValueError as exc:
        raise ReleaseError("the public key is not a PEM public key", cause=str(exc)) from exc
    _kind(key, crypto)
    return key


def load_private_key(pem: bytes) -> Any:
    """A PEM private key (unencrypted: a test key) of a kind a release is signed with."""
    crypto = _cryptography()
    try:
        key = crypto.serialization.load_pem_private_key(pem, password=None)
    except (ValueError, TypeError) as exc:
        raise ReleaseError("the signing key is not an unencrypted PEM private key", cause=str(exc)) from exc
    _kind(key, crypto)
    return key


def keyid(public_key: Any) -> str:
    """The hexadecimal SHA-256 of *public_key*'s DER ``SubjectPublicKeyInfo``."""
    crypto = _cryptography()
    der = public_key.public_bytes(
        crypto.serialization.Encoding.DER, crypto.serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return hashlib.sha256(der).hexdigest()


def sign_with_key(private_key: Any, payload: bytes) -> dict[str, str]:
    """One signature over *payload*'s PAE, made in this process with *private_key*."""
    crypto = _cryptography()
    message = pae(PAYLOAD_TYPE, payload)
    if _kind(private_key, crypto) == "ed25519":
        signature = private_key.sign(message)
    else:
        signature = private_key.sign(message, crypto.ec.ECDSA(crypto.hashes.SHA256()))
    return {"keyid": keyid(private_key.public_key()), "sig": base64.b64encode(signature).decode()}


def sign_with_command(argv: Sequence[str], payload: bytes) -> dict[str, str]:
    """One signature made by the signer *argv* names: the PAE on its stdin, JSON on its stdout.

    The production path: the key lives wherever that command reaches it (a KMS, an HSM, an
    agent), never in this process. The command answers ``{"keyid": ..., "sig": ...}``.
    """
    out = require(run(list(argv), stdin=pae(PAYLOAD_TYPE, payload)), "the signer")
    try:
        answer = json.loads(out)
        return {"keyid": str(answer["keyid"]), "sig": str(answer["sig"])}
    except (ValueError, KeyError, TypeError) as exc:
        raise ReleaseError('the signer did not answer {"keyid": ..., "sig": ...}') from exc


def envelope(payload: bytes, signatures: Sequence[dict[str, str]]) -> dict[str, Any]:
    """The DSSE envelope of *payload* and its *signatures*."""
    return {
        "payload": base64.b64encode(payload).decode(),
        "payloadType": PAYLOAD_TYPE,
        "signatures": list(signatures),
    }


def _verifies(key: Any, signature: bytes, message: bytes) -> bool:
    crypto = _cryptography()
    from cryptography.exceptions import InvalidSignature

    try:
        if _kind(key, crypto) == "ed25519":
            key.verify(signature, message)
        else:
            key.verify(signature, message, crypto.ec.ECDSA(crypto.hashes.SHA256()))
    except InvalidSignature:
        return False
    return True


def verify(raw: bytes, public_keys: Sequence[Any]) -> tuple[bytes, str]:
    """``(payload, keyid)``: the payload of the envelope *raw*, once a signature verifies.

    Refused, before anything is parsed of the payload: an envelope that is not DSSE's shape,
    another payload type, a payload or a signature that is not base64, no signature at all,
    and no signature that verifies against one of *public_keys* under its own ``keyid``.
    """
    _cryptography()
    if not public_keys:
        raise ReleaseError("no public key was given: a release is deployed only once it verifies")
    try:
        document = json.loads(raw)
    except ValueError as exc:
        raise ReleaseError("the envelope is not JSON") from exc
    if not isinstance(document, dict) or set(document) != {"payload", "payloadType", "signatures"}:
        raise ReleaseError("the envelope is not a DSSE envelope (payload, payloadType, signatures)")
    if document["payloadType"] != PAYLOAD_TYPE:
        raise ReleaseError(f"the envelope's payload is {document['payloadType']!r}, not a release manifest")
    signatures = document["signatures"]
    if not isinstance(signatures, list) or not signatures:
        raise ReleaseError("the envelope carries no signature")
    try:
        payload = base64.b64decode(str(document["payload"]), validate=True)
    except binascii.Error as exc:
        raise ReleaseError("the envelope's payload is not base64") from exc
    message = pae(PAYLOAD_TYPE, payload)
    keys = {keyid(key): key for key in public_keys}
    for signature in signatures:
        if not isinstance(signature, dict) or not isinstance(signature.get("sig"), str):
            raise ReleaseError("a signature of the envelope is not {keyid, sig}")
        key = keys.get(str(signature.get("keyid", "")))
        if key is None:
            continue
        try:
            raw_signature = base64.b64decode(signature["sig"], validate=True)
        except binascii.Error as exc:
            raise ReleaseError("a signature of the envelope is not base64") from exc
        if _verifies(key, raw_signature, message):
            return payload, str(signature["keyid"])
    raise ReleaseError(
        "no signature of the envelope verifies against the given public keys: it is unsigned, "
        "broken, or signed by a key this deployment does not trust"
    )


__all__ = [
    "PAYLOAD_TYPE",
    "envelope",
    "keyid",
    "load_private_key",
    "load_public_key",
    "pae",
    "require_cryptography",
    "sign_with_command",
    "sign_with_key",
    "verify",
]
