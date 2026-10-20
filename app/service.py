"""Business rules: issuing, anchoring, verifying and revoking records."""
from __future__ import annotations

import logging
import re
import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from .chain import ChainError
from .hashing import FIELD_LABELS, compute_hash, issuer_ref, new_salt, normalize, record_fields
from .store import Conflict

log = logging.getLogger("truemark.service")

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no I, L, O, 0, 1: easy to read off paper
CODE_RE = re.compile(r"^TM-\d{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$")
EDITABLE = ("institution", "student_name", "course", "grade", "issued_on")


class ValidationError(Exception):
    """Form input problem; the message is shown to the user."""


def normalize_code(raw: str) -> str:
    code = re.sub(r"[\s_‐-―]+", "-", (raw or "").strip().upper())
    return code if CODE_RE.match(code) else ""


def new_code() -> str:
    pick = lambda n: "".join(secrets.choice(CODE_ALPHABET) for _ in range(n))
    return f"TM-{datetime.now(timezone.utc).year}-{pick(4)}-{pick(4)}"


@dataclass
class VerifyResult:
    state: str  # valid | revoked | altered | pending | unavailable | not_found
    record: Optional[dict] = None
    chain: Optional[Any] = None
    fingerprint: str = ""
    error: str = ""


@dataclass
class CheckResult:
    state: str  # valid | revoked | invalid | pending | unavailable | not_found
    diffs: list[dict] = field(default_factory=list)
    presented: dict = field(default_factory=dict)
    error: str = ""


class Service:
    def __init__(self, store, chain) -> None:
        self.store = store
        self.chain = chain

    # ------------------------------------------------------------------ issuing
    @staticmethod
    def clean_issue_form(form: dict) -> dict:
        data = {
            "student_name": normalize(form.get("student_name")),
            "course": normalize(form.get("course")),
            "grade": normalize(form.get("grade")),
            "issued_on": normalize(form.get("issued_on")),
        }
        limits = {"student_name": 120, "course": 160, "grade": 40}
        labels = {"student_name": "Student name", "course": "Course or qualification", "grade": "Grade or result"}
        for key, limit in limits.items():
            if not data[key]:
                raise ValidationError(f"{labels[key]} is required.")
            if len(data[key]) > limit:
                raise ValidationError(f"{labels[key]} must be {limit} characters or fewer.")
        try:
            issued = date.fromisoformat(data["issued_on"])
        except ValueError:
            raise ValidationError("Enter the issue date as a valid date.") from None
        if issued > date.today() + timedelta(days=366):
            raise ValidationError("The issue date is too far in the future.")
        data["issued_on"] = issued.isoformat()
        return data

    def issue(self, issuer: dict, form: dict) -> dict:
        data = self.clean_issue_form(form)
        salt = new_salt()
        for _ in range(5):
            code = new_code()
            fields = {
                "record_code": code,
                "institution": issuer["institution_name"],
                "student_name": data["student_name"],
                "course": data["course"],
                "grade": data["grade"],
                "issued_on": data["issued_on"],
            }
            row = {
                "code": code,
                "issuer_id": issuer["id"],
                "institution_name": issuer["institution_name"],
                **data,
                "salt": salt,
                "record_hash": compute_hash(fields, salt),
                "status": "pending",
            }
            try:
                record = self.store.record_create(row)
                break
            except Conflict:
                continue
        else:  # pragma: no cover - 31^8 codes; effectively unreachable
            raise ValidationError("Could not generate a unique record ID. Try again.")
        self.store.audit_add(issuer["id"], issuer["email"], "record.issue", record["code"])
        return self.anchor(record, issuer)

    def anchor(self, record: dict, actor: dict) -> dict:
        """Write the fingerprint to the ledger. Returns the updated record; on failure it is marked 'failed'."""
        try:
            state = self.chain.lookup(record["record_hash"])
            if state.exists:  # an earlier attempt landed but we never saw the receipt
                fields = {
                    "status": "revoked" if state.revoked else "active",
                    "chain_name": self.chain.name,
                    "anchored_at": datetime.fromtimestamp(state.timestamp or 0, timezone.utc).isoformat(),
                    "anchor_error": None,
                }
            else:
                result = self.chain.anchor(record["record_hash"], issuer_ref(record["issuer_id"]))
                fields = {
                    "status": "active",
                    "tx_hash": result.tx_hash,
                    "block_number": result.block_number,
                    "chain_name": self.chain.name,
                    "anchored_at": datetime.fromtimestamp(result.timestamp, timezone.utc).isoformat(),
                    "anchor_error": None,
                }
            self.store.audit_add(actor["id"], actor["email"], "record.anchor", record["code"], fields.get("tx_hash") or "")
        except ChainError as exc:
            log.warning("anchor failed for %s: %s", record["code"], exc)
            fields = {"status": "failed", "anchor_error": str(exc)[:300]}
            self.store.audit_add(actor["id"], actor["email"], "record.anchor_failed", record["code"], str(exc)[:200])
        return self.store.record_update(record["id"], fields) or record

    # ------------------------------------------------------------------ verifying
    def verify(self, raw_code: str) -> VerifyResult:
        code = normalize_code(raw_code)
        record = self.store.record_get_by_code(code) if code else None
        if not record:
            return VerifyResult("not_found")
        if record["status"] in ("pending", "failed"):
            return VerifyResult("pending", record)
        # Recompute from what the database holds *now*. If anyone edited the row, this no longer
        # matches the anchored fingerprint, which is the whole point.
        fingerprint = compute_hash(record_fields(record), record["salt"])
        try:
            chain_state = self.chain.lookup(fingerprint)
        except ChainError as exc:
            return VerifyResult("unavailable", record, fingerprint=fingerprint, error=str(exc))
        if not chain_state.exists:
            return VerifyResult("altered", record, chain_state, fingerprint)
        if chain_state.revoked or record["status"] == "revoked":
            return VerifyResult("revoked", record, chain_state, fingerprint)
        return VerifyResult("valid", record, chain_state, fingerprint)

    def check_presented(self, raw_code: str, presented: dict) -> CheckResult:
        code = normalize_code(raw_code)
        record = self.store.record_get_by_code(code) if code else None
        if not record:
            return CheckResult("not_found")
        if record["status"] in ("pending", "failed"):
            return CheckResult("pending")
        shown = {key: normalize(presented.get(key)) for key in EDITABLE}
        original = record_fields(record)
        fields = {"record_code": record["code"], **shown}
        diffs = [
            {"field": key, "label": FIELD_LABELS[key], "original": normalize(original[key]), "presented": shown[key]}
            for key in EDITABLE
            if normalize(original[key]) != shown[key]
        ]
        try:
            state = self.chain.lookup(compute_hash(fields, record["salt"]))
        except ChainError as exc:
            return CheckResult("unavailable", presented=shown, error=str(exc))
        if state.exists and (state.revoked or record["status"] == "revoked"):
            return CheckResult("revoked", diffs, shown)
        if state.exists:
            return CheckResult("valid", diffs, shown)
        return CheckResult("invalid", diffs, shown)

    # ------------------------------------------------------------------ revoking
    def revoke(self, record: dict, reason: str, actor: dict) -> dict:
        reason = normalize(reason)
        if len(reason) < 3:
            raise ValidationError("Give a short reason for revoking this record.")
        if len(reason) > 300:
            raise ValidationError("The reason must be 300 characters or fewer.")
        if record["status"] != "active":
            raise ValidationError("Only active records can be revoked.")
        try:
            self.chain.revoke(record["record_hash"])
        except ChainError as exc:
            raise ValidationError(str(exc)) from exc
        updated = self.store.record_update(
            record["id"],
            {"status": "revoked", "revoked_at": datetime.now(timezone.utc).isoformat(), "revoked_reason": reason},
        )
        self.store.audit_add(actor["id"], actor["email"], "record.revoke", record["code"], reason)
        return updated or record

    # ------------------------------------------------------------------ stats
    def platform_stats(self) -> dict[str, int]:
        s = self.store
        return {
            "users": s.profile_count(),
            "pending_users": s.profile_count("pending"),
            "records": s.record_count(),
            "active": s.record_count(status="active"),
            "revoked": s.record_count(status="revoked"),
            "failed": s.record_count(status="failed"),
        }

    def issuer_stats(self, issuer_id: str) -> dict[str, int]:
        s = self.store
        return {
            "records": s.record_count(issuer_id=issuer_id),
            "active": s.record_count(issuer_id=issuer_id, status="active"),
            "revoked": s.record_count(issuer_id=issuer_id, status="revoked"),
            "failed": s.record_count(issuer_id=issuer_id, status="failed"),
        }
