"""In-memory session store.

Maps opaque session tokens to live NFVIS API objects.
Credentials never leave server memory — only the token is stored in the cookie.
"""

import secrets
from typing import Dict, Optional

# token → API instance
_sessions: Dict[str, object] = {}


def create(api_obj: object) -> str:
    """Store *api_obj* and return a new random session token."""
    token = secrets.token_hex(32)
    _sessions[token] = api_obj
    return token


def get(token: str) -> Optional[object]:
    """Return the API object for *token*, or None if not found."""
    return _sessions.get(token)


def delete(token: str) -> None:
    """Remove the session for *token* (logout)."""
    _sessions.pop(token, None)
