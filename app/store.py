"""Data storage.

Two interchangeable implementations with identical methods:
  * MemoryStore   - for local demos and tests (data disappears on restart)
  * SupabaseStore - talks to your Supabase Postgres through its REST API (PostgREST)
                    using the *secret* key, so it must only ever run on the server.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from .supa import api_headers


class StoreError(Exception):
    """The database could not complete the request."""


class Conflict(StoreError):
    """A unique value (for example a record code) already exists."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_q(q: str) -> str:
    # Characters with special meaning inside a PostgREST filter expression.
    return "".join(ch for ch in q if ch not in ",()*%\\").strip()


# --------------------------------------------------------------------------- memory


class MemoryStore:
    kind = "memory"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.profiles: dict[str, dict] = {}
        self.records: dict[str, dict] = {}
        self.audit: list[dict] = []
        self.ledger: dict[str, dict] = {}

    def ping(self) -> None:
        return None

    # profiles
    def profile_get(self, uid: str) -> Optional[dict]:
        with self._lock:
            row = self.profiles.get(uid)
            return dict(row) if row else None

    def profile_upsert(self, row: dict) -> dict:
        with self._lock:
            current = self.profiles.get(row["id"], {"created_at": now_iso(), "approved_at": None, "last_login_at": None})
            merged = {**current, **row}
            self.profiles[row["id"]] = merged
            return dict(merged)

    def profile_update(self, uid: str, fields: dict) -> Optional[dict]:
        with self._lock:
            if uid not in self.profiles:
                return None
            self.profiles[uid].update(fields)
            return dict(self.profiles[uid])

    def profile_list(self, status: Optional[str] = None, limit: int = 100, offset: int = 0) -> list[dict]:
        with self._lock:
            rows = [r for r in self.profiles.values() if not status or r["status"] == status]
            rows.sort(key=lambda r: r["created_at"], reverse=True)
            return [dict(r) for r in rows[offset : offset + limit]]

    def profile_count(self, status: Optional[str] = None) -> int:
        with self._lock:
            return sum(1 for r in self.profiles.values() if not status or r["status"] == status)

    # records
    def record_create(self, row: dict) -> dict:
        with self._lock:
            if any(r["code"] == row["code"] for r in self.records.values()):
                raise Conflict("Record code already exists")
            new = {
                "id": str(uuid.uuid4()),
                "created_at": now_iso(),
                "tx_hash": None,
                "block_number": None,
                "chain_name": None,
                "anchored_at": None,
                "revoked_at": None,
                "revoked_reason": None,
                "anchor_error": None,
                **row,
            }
            self.records[new["id"]] = new
            return dict(new)

    def record_get(self, rid: str) -> Optional[dict]:
        with self._lock:
            row = self.records.get(rid)
            return dict(row) if row else None

    def record_get_by_code(self, code: str) -> Optional[dict]:
        with self._lock:
            for row in self.records.values():
                if row["code"] == code:
                    return dict(row)
            return None

    def record_update(self, rid: str, fields: dict) -> Optional[dict]:
        with self._lock:
            if rid not in self.records:
                return None
            self.records[rid].update(fields)
            return dict(self.records[rid])

    def _record_filter(self, issuer_id: Optional[str], status: Optional[str], q: Optional[str]) -> list[dict]:
        needle = _clean_q(q or "").lower()
        rows = []
        for r in self.records.values():
            if issuer_id and r["issuer_id"] != issuer_id:
                continue
            if status and r["status"] != status:
                continue
            if needle and not any(needle in str(r[k]).lower() for k in ("code", "student_name", "course", "institution_name")):
                continue
            rows.append(r)
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        return rows

    def record_list(self, issuer_id=None, status=None, q=None, limit: int = 20, offset: int = 0) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._record_filter(issuer_id, status, q)[offset : offset + limit]]

    def record_count(self, issuer_id=None, status=None, q=None) -> int:
        with self._lock:
            return len(self._record_filter(issuer_id, status, q))

    # audit log
    def audit_add(self, actor_id: Optional[str], actor_email: str, action: str, target: str = "", detail: str = "") -> None:
        with self._lock:
            self.audit.append(
                {
                    "id": str(uuid.uuid4()),
                    "created_at": now_iso(),
                    "actor_id": actor_id,
                    "actor_email": actor_email,
                    "action": action,
                    "target": target,
                    "detail": detail,
                }
            )

    def audit_list(self, limit: int = 50, offset: int = 0) -> list[dict]:
        with self._lock:
            rows = sorted(self.audit, key=lambda r: r["created_at"], reverse=True)
            return [dict(r) for r in rows[offset : offset + limit]]

    def audit_count(self) -> int:
        with self._lock:
            return len(self.audit)

    # simulated ledger (only used when CHAIN_MODE=mock)
    def ledger_get(self, h: str) -> Optional[dict]:
        with self._lock:
            row = self.ledger.get(h)
            return dict(row) if row else None

    def ledger_put(self, h: str, issuer_ref: str, ts: int) -> None:
        with self._lock:
            if h in self.ledger:
                raise Conflict("Already anchored")
            self.ledger[h] = {"hash": h, "issuer_ref": issuer_ref, "ts": ts, "revoked": False}

    def ledger_revoke(self, h: str) -> None:
        with self._lock:
            if h in self.ledger:
                self.ledger[h]["revoked"] = True


# --------------------------------------------------------------------------- supabase


class SupabaseStore:
    kind = "supabase"

    def __init__(self, url: str, secret_key: str, transport: Optional[httpx.BaseTransport] = None) -> None:
        self.client = httpx.Client(
            base_url=url.rstrip("/") + "/rest/v1",
            headers={**api_headers(secret_key), "Content-Type": "application/json"},
            timeout=20,
            transport=transport,
        )

    # -- plumbing
    def _req(self, method: str, path: str, *, params=None, json=None, prefer: Optional[str] = None) -> httpx.Response:
        headers = {"Prefer": prefer} if prefer else {}
        try:
            resp = self.client.request(method, path, params=params, json=json, headers=headers)
        except httpx.HTTPError as exc:
            raise StoreError(f"Could not reach Supabase: {exc}") from exc
        if resp.status_code == 409:
            raise Conflict(resp.text[:200])
        if resp.status_code >= 400:
            raise StoreError(f"Supabase returned {resp.status_code}: {resp.text[:300]}")
        return resp

    def _one(self, resp: httpx.Response) -> Optional[dict]:
        rows = resp.json()
        return rows[0] if rows else None

    def _count(self, table: str, params: dict) -> int:
        resp = self._req("GET", f"/{table}", params={**params, "select": "id", "limit": 1}, prefer="count=exact")
        total = resp.headers.get("content-range", "*/0").split("/")[-1]
        return int(total) if total.isdigit() else 0

    def ping(self) -> None:
        self._req("GET", "/profiles", params={"select": "id", "limit": 1})

    # -- profiles
    def profile_get(self, uid: str) -> Optional[dict]:
        return self._one(self._req("GET", "/profiles", params={"id": f"eq.{uid}", "select": "*", "limit": 1}))

    def profile_upsert(self, row: dict) -> dict:
        resp = self._req(
            "POST",
            "/profiles",
            params={"on_conflict": "id"},
            json=row,
            prefer="resolution=merge-duplicates,return=representation",
        )
        return self._one(resp) or row

    def profile_update(self, uid: str, fields: dict) -> Optional[dict]:
        return self._one(self._req("PATCH", "/profiles", params={"id": f"eq.{uid}"}, json=fields, prefer="return=representation"))

    def profile_list(self, status: Optional[str] = None, limit: int = 100, offset: int = 0) -> list[dict]:
        params: dict[str, Any] = {"select": "*", "order": "created_at.desc", "limit": limit, "offset": offset}
        if status:
            params["status"] = f"eq.{status}"
        return self._req("GET", "/profiles", params=params).json()

    def profile_count(self, status: Optional[str] = None) -> int:
        return self._count("profiles", {"status": f"eq.{status}"} if status else {})

    # -- records
    def record_create(self, row: dict) -> dict:
        resp = self._req("POST", "/records", json=row, prefer="return=representation")
        created = self._one(resp)
        if not created:
            raise StoreError("Supabase did not return the new record.")
        return created

    def record_get(self, rid: str) -> Optional[dict]:
        return self._one(self._req("GET", "/records", params={"id": f"eq.{rid}", "select": "*", "limit": 1}))

    def record_get_by_code(self, code: str) -> Optional[dict]:
        return self._one(self._req("GET", "/records", params={"code": f"eq.{code}", "select": "*", "limit": 1}))

    def record_update(self, rid: str, fields: dict) -> Optional[dict]:
        return self._one(self._req("PATCH", "/records", params={"id": f"eq.{rid}"}, json=fields, prefer="return=representation"))

    def _record_params(self, issuer_id, status, q) -> dict:
        params: dict[str, Any] = {}
        if issuer_id:
            params["issuer_id"] = f"eq.{issuer_id}"
        if status:
            params["status"] = f"eq.{status}"
        needle = _clean_q(q or "")
        if needle:
            params["or"] = (
                f"(code.ilike.*{needle}*,student_name.ilike.*{needle}*,course.ilike.*{needle}*,institution_name.ilike.*{needle}*)"
            )
        return params

    def record_list(self, issuer_id=None, status=None, q=None, limit: int = 20, offset: int = 0) -> list[dict]:
        params = {**self._record_params(issuer_id, status, q), "select": "*", "order": "created_at.desc", "limit": limit, "offset": offset}
        return self._req("GET", "/records", params=params).json()

    def record_count(self, issuer_id=None, status=None, q=None) -> int:
        return self._count("records", self._record_params(issuer_id, status, q))

    # -- audit log
    def audit_add(self, actor_id: Optional[str], actor_email: str, action: str, target: str = "", detail: str = "") -> None:
        self._req(
            "POST",
            "/audit_log",
            json={"actor_id": actor_id, "actor_email": actor_email, "action": action, "target": target, "detail": detail},
        )

    def audit_list(self, limit: int = 50, offset: int = 0) -> list[dict]:
        return self._req("GET", "/audit_log", params={"select": "*", "order": "created_at.desc", "limit": limit, "offset": offset}).json()

    def audit_count(self) -> int:
        return self._count("audit_log", {})

    # -- simulated ledger
    def ledger_get(self, h: str) -> Optional[dict]:
        return self._one(self._req("GET", "/mock_ledger", params={"hash": f"eq.{h}", "select": "*", "limit": 1}))

    def ledger_put(self, h: str, issuer_ref: str, ts: int) -> None:
        self._req("POST", "/mock_ledger", json={"hash": h, "issuer_ref": issuer_ref, "ts": ts, "revoked": False})

    def ledger_revoke(self, h: str) -> None:
        self._req("PATCH", "/mock_ledger", params={"hash": f"eq.{h}"}, json={"revoked": True})
