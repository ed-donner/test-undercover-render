"""Checking a handler's sign-in: an access token from Supabase Auth, signed with one
of the project's public keys."""

import os
from functools import cache

import jwt

AUDIENCE = "authenticated"
# Seconds of difference allowed between Supabase's clock and ours.
CLOCK_LEEWAY = 30


class NotSignedIn(Exception):
    """The token isn't a valid sign-in."""


class OutOfReach(Exception):
    """Supabase's public keys couldn't be fetched to check a sign-in."""


@cache
def public_keys() -> jwt.PyJWKClient:
    """The Supabase project's public keys, at VITE_SUPABASE_URL. The client keeps the
    key set it fetches for five minutes, and fetches it again for a key it hasn't
    seen."""
    supabase_url = os.environ["VITE_SUPABASE_URL"]
    return jwt.PyJWKClient(f"{supabase_url}/auth/v1/.well-known/jwks.json")


def email_of(token: str) -> str:
    """Return the email of a valid, unexpired sign-in, or raise NotSignedIn, or
    OutOfReach when Supabase's keys can't be fetched: the sign-in may be fine."""
    try:
        key = public_keys().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key,
            algorithms=[key.algorithm_name],
            audience=AUDIENCE,
            leeway=CLOCK_LEEWAY,
            options={"require": ["exp", "email"]},
        )
    except jwt.PyJWKClientConnectionError as error:
        raise OutOfReach(str(error)) from error
    except jwt.PyJWTError as error:
        raise NotSignedIn(str(error)) from error
    return claims["email"]
