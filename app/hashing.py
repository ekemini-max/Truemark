"""Deterministic record fingerprints.

The fingerprint is SHA-256 over: salt + "|" + canonical JSON of the record fields.
The salt is random per record and stays in the database, so nobody can guess a
grade by hashing every possibility and comparing against the public chain.

app/static/js/demo.js implements the same recipe so the landing-page demo
produces identical fingerprints; tests/test_hashing.py checks that.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import unicodedata
from typing import Any, Mapping

# Every field that is covered by the fingerprint.
FIELDS = ("record_code", "institution", "student_name", "course", "grade", "issued_on")

FIELD_LABELS = {
    "institution": "Issued by",
    "student_name": "Student",
    "course": "Course",
    "grade": "Grade",
    "issued_on": "Issue date",
}


def normalize(value: Any) -> str:
    """Unicode-normalise and collapse whitespace so harmless differences never change the hash."""
    text = unicodedata.normalize("NFC", "" if value is None else str(value))
    return " ".join(text.split())


def canonical_json(fields: Mapping[str, Any]) -> str:
    data = {key: normalize(fields.get(key, "")) for key in FIELDS}
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def new_salt() -> str:
    return secrets.token_hex(16)


def compute_hash(fields: Mapping[str, Any], salt: str) -> str:
    payload = f"{salt}|{canonical_json(fields)}".encode("utf-8")
    return "0x" + hashlib.sha256(payload).hexdigest()


def issuer_ref(issuer_id: str) -> str:
    """Pseudonymous on-chain reference to an institution (never the name itself)."""
    return "0x" + hashlib.sha256(f"truemark-issuer:{issuer_id}".encode("utf-8")).hexdigest()


def record_fields(record: Mapping[str, Any]) -> dict[str, str]:
    """The hashed fields as stored on a database row."""
    return {
        "record_code": record["code"],
        "institution": record["institution_name"],
        "student_name": record["student_name"],
        "course": record["course"],
        "grade": record["grade"],
        "issued_on": str(record["issued_on"]),
    }
