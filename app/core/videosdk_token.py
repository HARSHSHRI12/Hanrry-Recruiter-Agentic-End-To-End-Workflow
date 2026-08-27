"""
VideoSDK Token Generator
Generates a fresh JWT token using API Key + Secret.

VideoSDK tokens expire — generate a new one programmatically instead of 
hard-coding. Token validity is set to 7 days by default.

Usage:
    from app.core.videosdk_token import get_videosdk_token
    token = get_videosdk_token()
"""
import os
import time
import jwt  # PyJWT
from app.core.logger import get_logger

log = get_logger(__name__)

# Cache: (token_string, expiry_timestamp)
_cached: tuple[str, float] = ("", 0.0)


def generate_token(
    api_key: str,
    secret: str,
    validity_seconds: int = 7 * 24 * 3600,  # 7 days
) -> str:
    """
    Generate a VideoSDK JWT using API Key + Secret.
    This is the correct way — never hard-code tokens.
    """
    now = int(time.time())
    payload = {
        "apikey": api_key,
        "permissions": ["allow_join"],  # Matching original token exactly
        "iat": now,
        "exp": now + validity_seconds,
    }
    token = jwt.encode(payload, secret, algorithm="HS256")
    # PyJWT >= 2.0 returns str, older returns bytes
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token


def get_videosdk_token() -> str:
    """
    Returns the VideoSDK token directly from .env to avoid JWT signing mismatches.
    """
    token = os.getenv("VIDEOSDK_AUTH_TOKEN", "").strip()
    if not token:
        log.error("VIDEOSDK_AUTH_TOKEN is missing from .env!")
    return token

