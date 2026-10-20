"""Public pages: landing, verification, QR codes, JSON API. No sign-in needed."""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from ..deps import ctx, qr_svg, redirect, render
from ..security import client_ip
from ..service import normalize_code

router = APIRouter()


def _limit(request: Request) -> None:
    ctx(request).limiter.hit(f"verify:{client_ip(request)}", 60, 60)


@router.get("/")
def home(request: Request):
    return render(request, "home.html")


@router.get("/verify")
def verify_lookup(request: Request, code: str = ""):
    if not code.strip():
        return redirect(request, "/", "Enter the record ID printed under the QR code, for example TM-2026-K7P4-9QXD.", "error")
    return redirect(request, f"/verify/{quote(normalize_code(code) or code.strip()[:40], safe='')}")


def _record_context(request: Request, code: str):
    c = ctx(request)
    result = c.service.verify(code)
    record = result.record
    public_record = None
    if record and result.state in ("valid", "revoked"):
        public_record = record
    explorer = c.chain.tx_url(record.get("tx_hash")) if record else None
    return {
        "result": result,
        "record": public_record,
        "code": normalize_code(code) or code[:40],
        "tx_url": explorer,
        "verify_url": f"{c.settings.base_url.rstrip('/')}/verify/{normalize_code(code)}",
    }


@router.get("/verify/{code}")
def verify_page(request: Request, code: str):
    _limit(request)
    return render(request, "verify.html", check=None, **_record_context(request, code))


@router.post("/verify/{code}/check")
def verify_check(
    request: Request,
    code: str,
    institution: str = Form(""),
    student_name: str = Form(""),
    course: str = Form(""),
    grade: str = Form(""),
    issued_on: str = Form(""),
):
    _limit(request)
    presented = {"institution": institution, "student_name": student_name, "course": course, "grade": grade, "issued_on": issued_on}
    check = ctx(request).service.check_presented(code, presented)
    return render(request, "verify.html", check=check, **_record_context(request, code))


@router.get("/api/verify/{code}")
def api_verify(request: Request, code: str):
    _limit(request)
    c = ctx(request)
    result = c.service.verify(code)
    body: dict = {"code": normalize_code(code), "status": result.state}
    record = result.record
    if record and result.state in ("valid", "revoked"):
        body["record"] = {
            "institution": record["institution_name"],
            "student_name": record["student_name"],
            "course": record["course"],
            "grade": record["grade"],
            "issued_on": str(record["issued_on"]),
            "revoked": result.state == "revoked",
        }
    if record and result.state in ("valid", "revoked", "altered"):
        body["proof"] = {
            "fingerprint": result.fingerprint,
            "ledger": c.chain.name,
            "simulated": c.chain.is_simulated,
            "anchored_at": record.get("anchored_at"),
            "tx_hash": record.get("tx_hash"),
            "tx_url": c.chain.tx_url(record.get("tx_hash")),
        }
    if result.error:
        body["error"] = result.error
    status = 404 if result.state == "not_found" else 200
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})


@router.get("/qr/{code}.svg")
def qr(request: Request, code: str):
    clean = normalize_code(code)
    if not clean:
        raise HTTPException(404, "Unknown record ID.")
    url = f"{ctx(request).settings.base_url.rstrip('/')}/verify/{clean}"
    return Response(qr_svg(url), media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/healthz")
def healthz(request: Request):
    c = ctx(request)
    try:
        c.store.ping()
        db = "ok"
    except Exception as exc:  # report, don't crash the probe
        db = f"error: {str(exc)[:120]}"
    return JSONResponse({"status": "ok" if db == "ok" else "degraded", "database": db, "ledger": c.chain.name})
