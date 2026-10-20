"""A small in-process imitation of the parts of Supabase (PostgREST + Auth) that TrueMark uses.

It lets the test-suite run the real SupabaseStore / SupabaseAuth code paths without a network.
It is deliberately strict: wrong API keys, unknown columns and CHECK-constraint violations are
rejected the way the real service rejects them, which is what catches typos in the client code.
Keep COLUMNS in sync with supabase/schema.sql.
"""
from __future__ import annotations

import json
import re
import secrets
import uuid
from datetime import datetime, timezone
from urllib.parse import unquote

import httpx

COLUMNS = {
    "profiles": ["id", "email", "full_name", "institution_name", "role", "status", "created_at", "approved_at", "last_login_at"],
    "records": [
        "id", "code", "issuer_id", "institution_name", "student_name", "course", "grade", "issued_on", "salt", "record_hash",
        "status", "tx_hash", "block_number", "chain_name", "anchored_at", "revoked_at", "revoked_reason", "anchor_error", "created_at",
    ],
    "audit_log": ["id", "created_at", "actor_id", "actor_email", "action", "target", "detail"],
    "mock_ledger": ["hash", "issuer_ref", "ts", "revoked"],
}
PK = {"profiles": "id", "records": "id", "audit_log": "id", "mock_ledger": "hash"}
UNIQUE = {"records": ["code"]}
NOT_NULL = {
    "profiles": ["id", "email"],
    "records": ["code", "issuer_id", "institution_name", "student_name", "course", "grade", "issued_on", "salt", "record_hash"],
    "audit_log": ["actor_email", "action"],
    "mock_ledger": ["hash", "issuer_ref", "ts"],
}
CHECKS = {
    "profiles": {"role": {"issuer", "admin"}, "status": {"pending", "approved", "suspended"}},
    "records": {"status": {"pending", "active", "revoked", "failed"}},
}
DEFAULTS = {
    "profiles": {"full_name": "", "institution_name": "", "role": "issuer", "status": "pending"},
    "records": {"status": "pending"},
    "mock_ledger": {"revoked": False},
}
RESERVED = {"select", "order", "limit", "offset", "on_conflict"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FakeSupabase:
    def __init__(self, secret_key: str = "sb_secret_test", publishable_key: str = "sb_publishable_test") -> None:
        self.secret_key, self.publishable_key = secret_key, publishable_key
        self.tables: dict[str, list[dict]] = {name: [] for name in COLUMNS}
        self.users: dict[str, dict] = {}
        self.tokens: dict[str, str] = {}  # access -> user id
        self.refresh: dict[str, str] = {}
        self.admin_users_allowed = True
        self.calls: list[tuple[str, str]] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    # ------------------------------------------------------------------ dispatcher
    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))
        if path.startswith("/rest/v1/"):
            return self._rest(request, path[len("/rest/v1/") :])
        if path.startswith("/auth/v1/"):
            return self._auth(request, path[len("/auth/v1") :])
        return httpx.Response(404, json={"message": "not found"})

    @staticmethod
    def _err(status: int, message: str, code: str = "") -> httpx.Response:
        return httpx.Response(status, json={"message": message, "code": code})

    # ------------------------------------------------------------------ PostgREST
    def _rest(self, request: httpx.Request, table: str) -> httpx.Response:
        if request.headers.get("apikey") != self.secret_key:
            return self._err(401, "Invalid API key")
        if table not in self.tables:
            return self._err(404, f"relation public.{table} does not exist", "42P01")
        params = dict(request.url.params)
        rows = self.tables[table]
        prefer = request.headers.get("Prefer", "")
        want_rows = "return=representation" in prefer

        if request.method == "GET":
            matched = self._filter(table, rows, params)
            if isinstance(matched, httpx.Response):
                return matched
            total = len(matched)
            if "order" in params:
                col, _, direction = params["order"].partition(".")
                matched = sorted(matched, key=lambda r: (r.get(col) is None, str(r.get(col))), reverse=direction == "desc")
            offset, limit = int(params.get("offset", 0)), params.get("limit")
            window = matched[offset : offset + int(limit)] if limit else matched[offset:]
            headers = {}
            if "count=exact" in prefer:
                headers["content-range"] = f"{offset}-{offset + len(window) - 1}/{total}" if window else f"*/{total}"
            return httpx.Response(200, json=[dict(r) for r in window], headers=headers)

        if request.method == "POST":
            body = json.loads(request.content or b"{}")
            items = body if isinstance(body, list) else [body]
            out = []
            for item in items:
                result = self._insert(table, item, upsert="merge-duplicates" in prefer, on_conflict=params.get("on_conflict"))
                if isinstance(result, httpx.Response):
                    return result
                out.append(result)
            return httpx.Response(201, json=[dict(r) for r in out] if want_rows else None)

        if request.method == "PATCH":
            matched = self._filter(table, rows, params)
            if isinstance(matched, httpx.Response):
                return matched
            patch = json.loads(request.content or b"{}")
            bad = [k for k in patch if k not in COLUMNS[table]]
            if bad:
                return self._err(400, f"Could not find the '{bad[0]}' column of '{table}' in the schema cache", "PGRST204")
            for row in matched:
                candidate = {**row, **patch}
                problem = self._constraints(table, candidate)
                if problem:
                    return problem
                row.update(patch)
            return httpx.Response(200, json=[dict(r) for r in matched] if want_rows else None)

        return self._err(405, "method not allowed")

    def _constraints(self, table: str, row: dict):
        for col in NOT_NULL.get(table, []):
            if row.get(col) is None:
                return self._err(400, f'null value in column "{col}" violates not-null constraint', "23502")
        for col, allowed in CHECKS.get(table, {}).items():
            if row.get(col) not in allowed:
                return self._err(400, f'new row violates check constraint "{table}_{col}_check"', "23514")
        return None

    def _insert(self, table: str, item: dict, upsert: bool, on_conflict):
        bad = [k for k in item if k not in COLUMNS[table]]
        if bad:
            return self._err(400, f"Could not find the '{bad[0]}' column of '{table}' in the schema cache", "PGRST204")
        row = {col: None for col in COLUMNS[table]}
        row.update(DEFAULTS.get(table, {}))
        if table in ("records", "audit_log"):
            row["id"] = str(uuid.uuid4())
        if table in ("records", "audit_log", "profiles"):
            row["created_at"] = _now()
        row.update(item)
        problem = self._constraints(table, row)
        if problem:
            return problem
        pk = PK[table]
        existing = next((r for r in self.tables[table] if r[pk] == row[pk]), None)
        if existing is not None:
            if upsert and (on_conflict or pk) == pk:
                existing.update({k: v for k, v in item.items()})
                return existing
            return self._err(409, f'duplicate key value violates unique constraint "{table}_pkey"', "23505")
        for col in UNIQUE.get(table, []):
            if any(r[col] == row[col] for r in self.tables[table]):
                return self._err(409, f'duplicate key value violates unique constraint "{table}_{col}_key"', "23505")
        self.tables[table].append(row)
        return row

    def _filter(self, table: str, rows: list[dict], params: dict):
        out = rows
        for key, expr in params.items():
            if key in RESERVED:
                continue
            if key == "or":
                out = [r for r in out if self._or(r, expr)]
                continue
            if key not in COLUMNS[table]:
                return self._err(400, f"column {table}.{key} does not exist", "42703")
            op, _, value = expr.partition(".")
            if op != "eq":
                return self._err(400, f"unsupported operator {op}", "PGRST100")
            out = [r for r in out if str(r.get(key)) == unquote(value)]
        return out

    @staticmethod
    def _or(row: dict, expr: str) -> bool:
        assert expr.startswith("(") and expr.endswith(")"), f"malformed or= filter: {expr}"
        for part in expr[1:-1].split(","):
            col, op, pattern = part.split(".", 2)
            assert op == "ilike", f"unsupported {op}"
            regex = "^" + re.escape(pattern).replace(r"\*", ".*") + "$"
            if re.match(regex, str(row.get(col) or ""), re.IGNORECASE):
                return True
        return False

    # ------------------------------------------------------------------ Auth
    def _auth(self, request: httpx.Request, path: str) -> httpx.Response:
        key = request.headers.get("apikey")
        body = json.loads(request.content) if request.content else {}
        params = dict(request.url.params)

        if path == "/admin/users" and request.method == "POST":
            if key != self.secret_key or not self.admin_users_allowed:
                return self._err(403, "User not allowed")
            email = (body.get("email") or "").lower()
            if email in self.users:
                return httpx.Response(422, json={"code": "email_exists", "msg": "A user with this email address has already been registered"})
            if len(body.get("password", "")) < 6:
                return httpx.Response(422, json={"code": "weak_password", "msg": "Password should be at least 6 characters."})
            user = {"id": str(uuid.uuid4()), "email": email, "password": body["password"], "user_metadata": body.get("user_metadata", {})}
            self.users[email] = user
            return httpx.Response(200, json=self._public(user))

        if key != self.publishable_key:
            return self._err(401, "Invalid API key")

        if path == "/token" and request.method == "POST":
            grant = params.get("grant_type")
            if grant == "password":
                user = self.users.get((body.get("email") or "").lower())
                if not user or user["password"] != body.get("password"):
                    return httpx.Response(400, json={"error_code": "invalid_credentials", "msg": "Invalid login credentials"})
            elif grant == "refresh_token":
                uid = self.refresh.pop(body.get("refresh_token", ""), None)
                user = next((u for u in self.users.values() if u["id"] == uid), None)
                if not user:
                    return httpx.Response(400, json={"error_code": "refresh_token_not_found", "msg": "Invalid Refresh Token"})
            else:
                return self._err(400, "unsupported grant_type")
            access, refresh = "at-" + secrets.token_urlsafe(24), "rt-" + secrets.token_urlsafe(24)
            self.tokens[access], self.refresh[refresh] = user["id"], user["id"]
            return httpx.Response(200, json={"access_token": access, "refresh_token": refresh, "expires_in": 3600, "user": self._public(user)})

        if path == "/user" and request.method == "GET":
            token = request.headers.get("Authorization", "").removeprefix("Bearer ")
            uid = self.tokens.get(token)
            user = next((u for u in self.users.values() if u["id"] == uid), None)
            if not user:
                return httpx.Response(401, json={"msg": "invalid JWT"})
            return httpx.Response(200, json=self._public(user))

        if path == "/logout" and request.method == "POST":
            self.tokens.pop(request.headers.get("Authorization", "").removeprefix("Bearer "), None)
            return httpx.Response(204)

        return self._err(404, "not found")

    @staticmethod
    def _public(user: dict) -> dict:
        return {"id": user["id"], "email": user["email"], "user_metadata": user["user_metadata"]}

    def expire_access_tokens(self) -> None:
        self.tokens.clear()
