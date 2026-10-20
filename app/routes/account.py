"""Accounts and the school (issuer) workspace."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request

from ..auth import AuthError
from ..deps import (
    AT_COOKIE,
    RT_COOKIE,
    NotApproved,
    can_access,
    ctx,
    current_user,
    ensure_profile,
    qr_svg,
    redirect,
    render,
    require_approved,
    require_user,
    safe_next,
)
from ..security import client_ip, csrf_protect
from ..service import ValidationError

router = APIRouter()
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PAGE_SIZE = 15


def _start_session(request: Request, response, session) -> None:
    secure = ctx(request).settings.cookie_secure
    for name, value in ((AT_COOKIE, session.access_token), (RT_COOKIE, session.refresh_token)):
        response.set_cookie(name, value, max_age=60 * 60 * 24 * 30, httponly=True, samesite="lax", secure=secure, path="/")


# ----------------------------------------------------------------------------- sign up / in / out


@router.get("/signup")
def signup_page(request: Request):
    if current_user(request):
        return redirect(request, "/dashboard")
    return render(request, "signup.html", form={}, error=None, signups_open=ctx(request).settings.allow_signup)


@router.post("/signup", dependencies=[Depends(csrf_protect)])
def signup(
    request: Request,
    full_name: str = Form(""),
    institution_name: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
):
    c = ctx(request)
    c.limiter.hit(f"signup:{client_ip(request)}", 8, 3600)
    form = {"full_name": full_name.strip(), "institution_name": institution_name.strip(), "email": email.strip().lower()}
    error = None
    if not c.settings.allow_signup:
        error = "New registrations are closed."
    elif not form["full_name"] or not form["institution_name"]:
        error = "Enter your name and your institution's name."
    elif len(form["institution_name"]) > 160 or len(form["full_name"]) > 120:
        error = "That name is too long."
    elif not EMAIL_RE.match(form["email"]):
        error = "Enter a valid email address."
    elif len(password) < 8:
        error = "Use a password with at least 8 characters."
    elif form["email"] in c.settings.admin_email_set and not c.auth.allow_admin_signup:
        error = "This email is reserved for an admin. Sign in instead."
    if error:
        return render(request, "signup.html", status_code=400, form=form, error=error, signups_open=c.settings.allow_signup)
    try:
        user = c.auth.sign_up(form["email"], password, form["full_name"], form["institution_name"])
        _, session = c.auth.sign_in(form["email"], password)
    except AuthError as exc:
        return render(request, "signup.html", status_code=400, form=form, error=str(exc), signups_open=True)
    profile = ensure_profile(c, user)
    c.store.audit_add(user.id, user.email, "user.signup", form["institution_name"])
    response = redirect(request, "/dashboard", "Account created." if profile["status"] == "approved" else "Account created. An admin will review it shortly.")
    _start_session(request, response, session)
    return response


@router.get("/login")
def login_page(request: Request, next: str = "/dashboard"):
    if current_user(request):
        return redirect(request, safe_next(next))
    return render(request, "login.html", error=None, email="", next=safe_next(next))


@router.post("/login", dependencies=[Depends(csrf_protect)])
def login(request: Request, email: str = Form(""), password: str = Form(""), next: str = Form("/dashboard")):
    c = ctx(request)
    email = email.strip().lower()
    c.limiter.hit(f"login:{client_ip(request)}", 10, 600)
    c.limiter.hit(f"login-email:{email}", 8, 600)
    try:
        user, session = c.auth.sign_in(email, password)
    except AuthError as exc:
        return render(request, "login.html", status_code=401, error=str(exc), email=email, next=safe_next(next))
    profile = ensure_profile(c, user)
    c.store.profile_update(profile["id"], {"last_login_at": datetime.now(timezone.utc).isoformat()})
    response = redirect(request, safe_next(next))
    _start_session(request, response, session)
    return response


@router.post("/logout", dependencies=[Depends(csrf_protect)])
def logout(request: Request):
    at = request.cookies.get(AT_COOKIE)
    if at:
        ctx(request).auth.sign_out(at)
    response = redirect(request, "/", "You are signed out.")
    request.state.clear_session = True
    return response


# ----------------------------------------------------------------------------- workspace


@router.get("/dashboard")
def dashboard(request: Request, q: str = "", page: int = 1):
    user = require_user(request)
    if user["status"] != "approved":
        return render(request, "pending.html", status_code=200)
    c = ctx(request)
    page = max(page, 1)
    owner = user["id"]  # admins see every record under /admin/records
    records = c.store.record_list(issuer_id=owner, q=q, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE)
    total = c.store.record_count(issuer_id=owner, q=q)
    return render(
        request,
        "dashboard.html",
        records=records,
        total=total,
        stats=c.service.issuer_stats(user["id"]),
        q=q,
        page=page,
        pages=max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1),
    )


@router.get("/issue")
def issue_page(request: Request):
    user = require_approved(request)
    return render(request, "issue.html", form={"issued_on": date.today().isoformat()}, error=None, institution=user["institution_name"])


@router.post("/issue", dependencies=[Depends(csrf_protect)])
def issue(
    request: Request,
    student_name: str = Form(""),
    course: str = Form(""),
    grade: str = Form(""),
    issued_on: str = Form(""),
):
    user = require_approved(request)
    c = ctx(request)
    c.limiter.hit(f"issue:{user['id']}", 60, 600)
    form = {"student_name": student_name, "course": course, "grade": grade, "issued_on": issued_on}
    try:
        record = c.service.issue(user, form)
    except ValidationError as exc:
        return render(request, "issue.html", status_code=400, form=form, error=str(exc), institution=user["institution_name"])
    if record["status"] == "active":
        return redirect(request, f"/records/{record['id']}", "Record issued and anchored.")
    return redirect(request, f"/records/{record['id']}", "Record saved, but anchoring failed. You can retry from this page.", "error")


def _own_record(request: Request, rid: str) -> tuple[dict, dict]:
    user = require_approved(request)
    record = ctx(request).store.record_get(rid)
    if not record or not can_access(user, record):
        raise HTTPException(404, "Record not found.")
    return user, record


@router.get("/records/{rid}")
def record_page(request: Request, rid: str):
    user, record = _own_record(request, rid)
    c = ctx(request)
    verify_url = f"{c.settings.base_url.rstrip('/')}/verify/{record['code']}"
    return render(
        request,
        "record.html",
        record=record,
        verify_url=verify_url,
        qr=qr_svg(verify_url),
        tx_url=c.chain.tx_url(record.get("tx_hash")),
        error=None,
    )


@router.get("/records/{rid}/certificate")
def certificate(request: Request, rid: str):
    user, record = _own_record(request, rid)
    c = ctx(request)
    if record["status"] not in ("active", "revoked"):
        raise HTTPException(409, "This record is not anchored yet, so it has no certificate.")
    verify_url = f"{c.settings.base_url.rstrip('/')}/verify/{record['code']}"
    return render(request, "certificate.html", record=record, verify_url=verify_url, qr=qr_svg(verify_url))


@router.post("/records/{rid}/anchor", dependencies=[Depends(csrf_protect)])
def retry_anchor(request: Request, rid: str):
    user, record = _own_record(request, rid)
    if record["status"] not in ("pending", "failed"):
        return redirect(request, f"/records/{rid}", "This record is already anchored.", "error")
    updated = ctx(request).service.anchor(record, user)
    if updated["status"] == "active":
        return redirect(request, f"/records/{rid}", "Record anchored.")
    return redirect(request, f"/records/{rid}", updated.get("anchor_error") or "Anchoring failed again.", "error")


@router.post("/records/{rid}/revoke", dependencies=[Depends(csrf_protect)])
def revoke(request: Request, rid: str, reason: str = Form("")):
    user, record = _own_record(request, rid)
    try:
        ctx(request).service.revoke(record, reason, user)
    except ValidationError as exc:
        return redirect(request, f"/records/{rid}", str(exc), "error")
    return redirect(request, f"/records/{rid}", "Record revoked. The public page now shows it as revoked.")
