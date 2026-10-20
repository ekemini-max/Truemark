"""Tiny helpers shared by the Supabase store and auth clients."""
from __future__ import annotations


def api_headers(key: str) -> dict[str, str]:
    """Headers that authenticate a request with a Supabase API key.

    New-style keys (sb_publishable_... / sb_secret_...) are not JWTs and go in `apikey` only.
    Legacy keys (anon / service_role) are JWTs starting with "eyJ"; they are sent in both headers.
    """
    headers = {"apikey": key}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    return headers
