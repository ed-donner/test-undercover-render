"""Signing in as a handler in the tests, with tokens signed by a key pair made here
in place of Supabase's."""

import time

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

from backend.auth import AUDIENCE

# The Supabase project the tests stand in for.
SUPABASE_URL = "https://supabase.test"
DANA = "dana.whitfield@undercover.example"
MARCUS = "marcus.oyelaran@undercover.example"

KEY_ID = "test-key"
KEY = ec.generate_private_key(ec.SECP256R1())
# Another key, which Supabase never published, under the same id.
OTHER_KEY = ec.generate_private_key(ec.SECP256R1())

# The public keys the tests publish in place of Supabase's.
PUBLIC_KEYS = {
    "keys": [
        ECAlgorithm.to_jwk(KEY.public_key(), as_dict=True)
        | {"kid": KEY_ID, "alg": "ES256", "use": "sig"}
    ]
}


def token(
    email: str,
    key: ec.EllipticCurvePrivateKey = KEY,
    audience: str = AUDIENCE,
    expires_in: int = 3600,
    issued_in: int = 0,
) -> str:
    """A Supabase access token for an email, as Supabase Auth signs one, issued now
    by Supabase's clock, or that many seconds ahead of ours."""
    issued = int(time.time()) + issued_in
    claims = {
        "sub": email,
        "email": email,
        "aud": audience,
        "role": "authenticated",
        "iat": issued,
        "exp": issued + expires_in,
    }
    return jwt.encode(claims, key, algorithm="ES256", headers={"kid": KEY_ID})


def signed_in(email: str = DANA, **options) -> dict[str, str]:
    """The headers of a request from the handler with this email."""
    return {"Authorization": f"Bearer {token(email, **options)}"}
