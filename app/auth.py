"""Sign-in providers.

  * SupabaseAuth - uses Supabase Auth (GoTrue) over its REST API.
  * LocalAuth    - in-memory accounts for local demos and tests only.

New accounts are created through the admin endpoint with the email pre-confirmed.
That avoids Supabase's tiny free-tier email quota; instead, every new account waits
for a TrueMark admin to approve it before it can issue anything.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

import httpx

from .supa import api_headers


class AuthError(Exception):
    """Raised with a message that is safe to show to the person signing in."""


@dataclass
class AuthUser:
    id: str
    email: str
    meta: dict = field(default_factory=dict)


@dataclass
class AuthSession:
    access_token: str
    refresh_token: str
    expires_in: int = 3600


# --------------------------------------------------------------------------- supabase


class SupabaseAuth:
    kind = "supabase"
    allow_admin_signup = False

    def __init__(self, url: str, publishable_key: str, secret_key: str, transport: Optional[httpx.BaseTransport] = None) -> None:
        self.base = url.rstrip("/") + "/auth/v1"
        self.publishable_key = publishable_key
        self.secret_key = secret_key
        self.client = httpx.Client(timeout=20, transport=transport)
        self._cache: dict[str, tuple[float, AuthUser]] = {}
        self._lock = threading.Lock()

    def _call(self, method: str, path: str, *, key: str, bearer: Optional[str] = None, **kwargs) -> httpx.Response:
        headers = api_headers(key)
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        try:
            return self.client.request(method, self.base + path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise AuthError("Sign-in service is unreachable right now. Try again in a minute.") from exc

    @staticmethod
    def _user(data: dict) -> AuthUser:
        return AuthUser(id=data["id"], email=(data.get("email") or "").lower(), meta=data.get("user_metadata") or {})

    def sign_up(self, email: str, password: str, full_name: str, institution_name: str) -> AuthUser:
        resp = self._call(
            "POST",
            "/admin/users",
            key=self.secret_key,
            json={
                "email": email,
                "password": password,
                "email_confirm": True,
                "user_metadata": {"full_name": full_name, "institution_name": institution_name},
            },
        )
        if resp.status_code in (200, 201):
            return self._user(resp.json())
        body = resp.text.lower()
        if resp.status_code == 422 and ("already" in body or "exists" in body or "registered" in body):
            raise AuthError("An account with this email already exists. Sign in instead.")
        if resp.status_code == 422 and "password" in body:
            raise AuthError("That password is too weak. Use at least 8 characters.")
        if resp.status_code in (401, 403):
            raise AuthError("The server's Supabase secret key was rejected. Check SUPABASE_SECRET_KEY.")
        raise AuthError("Could not create the account. Try again.")

    def sign_in(self, email: str, password: str) -> tuple[AuthUser, AuthSession]:
        resp = self._call(
            "POST", "/token", key=self.publishable_key, params={"grant_type": "password"}, json={"email": email, "password": password}
        )
        if resp.status_code != 200:
            if resp.status_code in (400, 401, 422):
                raise AuthError("Email or password is incorrect.")
            raise AuthError("Could not sign in. Try again.")
        data = resp.json()
        return self._user(data["user"]), AuthSession(data["access_token"], data["refresh_token"], int(data.get("expires_in", 3600)))

    def get_user(self, access_token: str) -> AuthUser:
        key = hashlib.sha256(access_token.encode()).hexdigest()
        now = time.time()
        with self._lock:
            hit = self._cache.get(key)
            if hit and hit[0] > now:
                return hit[1]
        resp = self._call("GET", "/user", key=self.publishable_key, bearer=access_token)
        if resp.status_code != 200:
            raise AuthError("Session expired.")
        user = self._user(resp.json())
        with self._lock:
            if len(self._cache) > 500:
                self._cache.clear()
            self._cache[key] = (now + 60, user)
        return user

    def refresh(self, refresh_token: str) -> tuple[AuthUser, AuthSession]:
        resp = self._call(
            "POST", "/token", key=self.publishable_key, params={"grant_type": "refresh_token"}, json={"refresh_token": refresh_token}
        )
        if resp.status_code != 200:
            raise AuthError("Session expired.")
        data = resp.json()
        return self._user(data["user"]), AuthSession(data["access_token"], data["refresh_token"], int(data.get("expires_in", 3600)))

    def sign_out(self, access_token: str) -> None:
        try:
            self._call("POST", "/logout", key=self.publishable_key, bearer=access_token)
        except AuthError:
            pass
        with self._lock:
            self._cache.pop(hashlib.sha256(access_token.encode()).hexdigest(), None)


# --------------------------------------------------------------------------- local (dev/tests)


class LocalAuth:
    kind = "local"
    allow_admin_signup = True  # local demos only: lets you create the first admin without Supabase

    def __init__(self) -> None:
        self._users: dict[str, dict] = {}
        self._tokens: dict[str, tuple[str, float]] = {}
        self._refresh: dict[str, str] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _hash(password: str, salt: bytes) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 50_000)

    def sign_up(self, email: str, password: str, full_name: str, institution_name: str) -> AuthUser:
        with self._lock:
            if email in self._users:
                raise AuthError("An account with this email already exists. Sign in instead.")
            salt = secrets.token_bytes(16)
            uid = str(uuid.uuid4())
            self._users[email] = {
                "id": uid,
                "salt": salt,
                "hash": self._hash(password, salt),
                "meta": {"full_name": full_name, "institution_name": institution_name},
            }
            return AuthUser(uid, email, dict(self._users[email]["meta"]))

    def _issue(self, email: str) -> AuthSession:
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self._lock:
            self._tokens[access] = (email, time.time() + 3600)
            self._refresh[refresh] = email
        return AuthSession(access, refresh, 3600)

    def sign_in(self, email: str, password: str) -> tuple[AuthUser, AuthSession]:
        with self._lock:
            row = self._users.get(email)
        if not row or not hmac.compare_digest(row["hash"], self._hash(password, row["salt"])):
            raise AuthError("Email or password is incorrect.")
        return AuthUser(row["id"], email, dict(row["meta"])), self._issue(email)

    def _user_for(self, email: str) -> AuthUser:
        row = self._users[email]
        return AuthUser(row["id"], email, dict(row["meta"]))

    def get_user(self, access_token: str) -> AuthUser:
        with self._lock:
            hit = self._tokens.get(access_token)
            if not hit or hit[1] < time.time():
                raise AuthError("Session expired.")
            return self._user_for(hit[0])

    def refresh(self, refresh_token: str) -> tuple[AuthUser, AuthSession]:
        with self._lock:
            email = self._refresh.pop(refresh_token, None)
        if not email:
            raise AuthError("Session expired.")
        return self._user_for(email), self._issue(email)

    def sign_out(self, access_token: str) -> None:
        with self._lock:
            self._tokens.pop(access_token, None)

    def expire_access_tokens(self) -> None:
        """Test helper: simulate access tokens timing out."""
        with self._lock:
            self._tokens.clear()
