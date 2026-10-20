"""Admin console: approve schools, oversee records, read the audit trail, check system health."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request

from ..deps import ctx, redirect, render, require_admin
from ..security import csrf_protect

router = APIRouter(prefix="/admin")
PAGE_SIZE = 25


@router.get("")
def overview(request: Request):
    require_admin(request)
    c = ctx(request)
    return render(
        request,
        "admin_overview.html",
        stats=c.service.platform_stats(),
        pending=c.store.profile_list(status="pending", limit=10),
        recent=c.store.audit_list(limit=8),
        problems=c.settings.problems(),
        chain_status=c.chain.status(),
        storage=c.store.kind,
    )


@router.get("/users")
def users(request: Request, status: str = "", page: int = 1):
    require_admin(request)
    c = ctx(request)
    status = status if status in ("pending", "approved", "suspended") else ""
    page = max(page, 1)
    rows = c.store.profile_list(status=status or None, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE)
    total = c.store.profile_count(status or None)
    return render(request, "admin_users.html", rows=rows, status=status, page=page, pages=max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1), total=total)


@router.post("/users/{uid}/status", dependencies=[Depends(csrf_protect)])
def set_status(request: Request, uid: str, status: str = Form(""), back: str = Form("/admin/users")):
    admin = require_admin(request)
    c = ctx(request)
    back = back if back.startswith("/admin") and not back.startswith("//") and "\\" not in back else "/admin/users"
    if status not in ("approved", "suspended"):
        raise HTTPException(400, "Unknown status.")
    if uid == admin["id"]:
        return redirect(request, back, "You cannot change your own access.", "error")
    target = c.store.profile_get(uid)
    if not target:
        raise HTTPException(404, "User not found.")
    fields = {"status": status}
    if status == "approved" and not target.get("approved_at"):
        fields["approved_at"] = datetime.now(timezone.utc).isoformat()
    c.store.profile_update(uid, fields)
    c.store.audit_add(admin["id"], admin["email"], f"user.{status}", target["email"], target["institution_name"])
    verb = "approved" if status == "approved" else "suspended"
    return redirect(request, back, f"{target['institution_name'] or target['email']} {verb}.")


@router.post("/users/{uid}/role", dependencies=[Depends(csrf_protect)])
def set_role(request: Request, uid: str, role: str = Form("")):
    admin = require_admin(request)
    c = ctx(request)
    if role not in ("admin", "issuer"):
        raise HTTPException(400, "Unknown role.")
    target = c.store.profile_get(uid)
    if not target:
        raise HTTPException(404, "User not found.")
    if uid == admin["id"]:
        return redirect(request, "/admin/users", "You cannot change your own role.", "error")
    if role == "issuer" and target["email"].lower() in c.settings.admin_email_set:
        return redirect(request, "/admin/users", "This email is listed in ADMIN_EMAILS. Remove it there first.", "error")
    fields = {"role": role}
    if role == "admin":
        fields["status"] = "approved"
    c.store.profile_update(uid, fields)
    c.store.audit_add(admin["id"], admin["email"], f"user.role_{role}", target["email"])
    return redirect(request, "/admin/users", f"{target['email']} is now {'an admin' if role == 'admin' else 'a school account'}.")


@router.get("/records")
def records(request: Request, q: str = "", status: str = "", page: int = 1):
    require_admin(request)
    c = ctx(request)
    status = status if status in ("active", "revoked", "pending", "failed") else ""
    page = max(page, 1)
    rows = c.store.record_list(status=status or None, q=q, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE)
    total = c.store.record_count(status=status or None, q=q)
    return render(
        request,
        "admin_records.html",
        rows=rows,
        q=q,
        status=status,
        total=total,
        page=page,
        pages=max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1),
    )


@router.get("/audit")
def audit(request: Request, page: int = 1):
    require_admin(request)
    c = ctx(request)
    page = max(page, 1)
    rows = c.store.audit_list(limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE)
    total = c.store.audit_count()
    return render(request, "admin_audit.html", rows=rows, page=page, pages=max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1))
