"""Prove the JWT signature is now verified (fix for the forged-token hole).

A token must be signed by the realm key from the JWKS before its claims are
trusted. Prior behavior base64-decoded the payload with no signature check,
so anyone could mint an operator token.
"""

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from fastapi import Request

import apps.api.main as main_module
from apps.api.main import get_current_user


def _rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    numbers = public_key.public_numbers()
    return private_key, {
        "kty": "RSA",
        "kid": "realm-key-1",
        "use": "sig",
        "alg": "RS256",
        "n": _b64(numbers.n),
        "e": _b64(numbers.e),
    }


def _b64(value):
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return jwt.utils.base64url_encode(raw).decode()


def _token(private_key, kid, claims):
    return jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )


_FUTURE_EXP = 2**31  # far-future unix timestamp, PyJWT 2.x expects ints


def _request_with(token: bytes) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v1/test",
            "headers": [(b"authorization", b"Bearer " + token)],
        }
    )


@pytest.mark.asyncio
async def test_valid_operator_token_accepted(monkeypatch):
    private_key, jwk = _rsa_keypair()
    monkeypatch.setattr(main_module, "get_jwks", lambda: {"keys": [jwk]})
    token = _token(
        private_key,
        jwk["kid"],
        {
            "sub": "u-1",
            "preferred_username": "op1",
            "realm_access": {"roles": ["operator"]},
            "exp": _FUTURE_EXP,
        },
    )

    user = await get_current_user(_request_with(token.encode()))

    assert user["subject"] == "u-1"
    assert user["role"] == "operator"


@pytest.mark.asyncio
async def test_forged_token_with_attacker_key_rejected(monkeypatch):
    # The exact attack: a real-looking payload signed by the ATTACKER's key.
    realm_private, realm_jwk = _rsa_keypair()
    attacker_private, _ = _rsa_keypair()  # attacker key is not in the JWKS
    monkeypatch.setattr(main_module, "get_jwks", lambda: {"keys": [realm_jwk]})
    token = _token(
        attacker_private,
        realm_jwk["kid"],  # kid spoofed to match the realm key
        {
            "sub": "attacker",
            "preferred_username": "attacker",
            "realm_access": {"roles": ["operator"]},
            "exp": _FUTURE_EXP,
        },
    )

    with pytest.raises(Exception) as exc_info:
        await get_current_user(_request_with(token.encode()))
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_unknown_kid_rejected(monkeypatch):
    private_key, jwk = _rsa_keypair()
    monkeypatch.setattr(main_module, "get_jwks", lambda: {"keys": [jwk]})
    token = _token(
        private_key,
        "some-other-kid",
        {"sub": "u-1", "exp": _FUTURE_EXP},
    )

    with pytest.raises(Exception) as exc_info:
        await get_current_user(_request_with(token.encode()))
    # Rejected before any signature attempt: 401 for unknown key id.
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_expired_token_rejected(monkeypatch):
    private_key, jwk = _rsa_keypair()
    monkeypatch.setattr(main_module, "get_jwks", lambda: {"keys": [jwk]})
    token = _token(
        private_key,
        jwk["kid"],
        {"sub": "u-1", "exp": 1},  # long-expired
    )

    with pytest.raises(Exception) as exc_info:
        await get_current_user(_request_with(token.encode()))
    assert exc_info.value.status_code == 403
