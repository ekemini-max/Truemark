"""Request context, sessions, permissions and template rendering."""
from __future__ import annotations

import io
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, unquote

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from .auth import AuthError, AuthUser
from .config import Settings
from .security import RateLimiter
from .service import Service

log = logging.getLogger("truemark.deps")

APP_DIR = Path(__file__).resolve().parent
AT_COOKIE, RT_COOKIE, FLASH_COOKIE = "tm_at", "tm_rt", "tm_flash"
SESSION_MAX_AGE = 60 * 60 * 24 * 30


@dataclass
class AppContext:
    settings: Settings
    store: Any
    chain: Any
    auth: Any
    service: Service
    limiter: RateLimiter
    templates: Jinja2Templates


def ctx(request: Request) -> AppContext:
    return request.app.state.ctx


# ----------------------------------------------------------------------------- redirects & flash


class Redirect(Exception):
    def __init__(self, url: str, flash: Optional[str] = None, kind: str = "ok") -> None:
        self.url, self.flash, self.kind = url, flash, kind


def safe_next(value: Optional[str], default: str = "/dashboard") -> str:
    if value and value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return default


def redirect(request: Request, url: str, flash: Optional[str] = None, kind: str = "ok") -> RedirectResponse:
    response = RedirectResponse(url, status_code=303)
    if flash:
        response.set_cookie(
            FLASH_COOKIE,
            quote(json.dumps({"text": flash, "kind": kind})),
            max_age=60,
            httponly=True,
            samesite="lax",
            secure=ctx(request).settings.cookie_secure,
        )
        request.state.flash_set = True
    return response


def read_flash(request: Request) -> Optional[dict]:
    raw = request.cookies.get(FLASH_COOKIE)
    if not raw:
        return None
    try:
        data = json.loads(unquote(raw))
        return {"text": str(data["text"])[:300], "kind": "error" if data.get("kind") == "error" else "ok"}
    except (ValueError, KeyError, TypeError):
        return None


# ----------------------------------------------------------------------------- sessions


def ensure_profile(c: AppContext, user: AuthUser) -> dict:
    """Return the profile row for an authenticated user, creating or upgrading it when needed."""
    profile = c.store.profile_get(user.id)
    is_admin_email = user.email.lower() in c.settings.admin_email_set
    if profile is None:
        profile = c.store.profile_upsert(
            {
                "id": user.id,
                "email": user.email,
                "full_name": str(user.meta.get("full_name", ""))[:120],
                "institution_name": str(user.meta.get("institution_name", ""))[:160],
                "role": "admin" if is_admin_email else "issuer",
                "status": "approved" if is_admin_email else "pending",
            }
        )
    elif is_admin_email and (profile["role"] != "admin" or profile["status"] != "approved"):
        profile = c.store.profile_update(user.id, {"role": "admin", "status": "approved"}) or profile
    return profile


def current_user(request: Request) -> Optional[dict]:
    """The signed-in profile (or None). Refreshes expired access tokens transparently."""
    if hasattr(request.state, "user_resolved"):
        return request.state.user
    c = ctx(request)
    at, rt = request.cookies.get(AT_COOKIE), request.cookies.get(RT_COOKIE)
    user: Optional[AuthUser] = None
    if at:
        try:
            user = c.auth.get_user(at)
        except AuthError:
            user = None
    if user is None and rt:
        try:
            user, session = c.auth.refresh(rt)
            request.state.new_session = session
        except AuthError:
            user = None
    if user is None and (at or rt):
        request.state.clear_session = True
    profile = ensure_profile(c, user) if user else None
    request.state.user_resolved = True
    request.state.user = profile
    return profile


def require_user(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise Redirect(f"/login?next={quote(request.url.path)}")
    return user


class NotApproved(Exception):
    def __init__(self, user: dict) -> None:
        self.user = user


def require_approved(request: Request) -> dict:
    user = require_user(request)
    if user["status"] != "approved":
        raise NotApproved(user)
    return user


def require_admin(request: Request) -> dict:
    user = require_approved(request)
    if user["role"] != "admin":
        raise HTTPException(403, "Only TrueMark admins can open this page.")
    return user


def can_access(user: dict, record: dict) -> bool:
    return user["role"] == "admin" or record["issuer_id"] == user["id"]


# ----------------------------------------------------------------------------- rendering


def _fmt_date(value: Any) -> str:
    if not value:
        return ""
    try:
        d = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
        return f"{d.day} {d:%B %Y}"
    except ValueError:
        return str(value)


def _fmt_dt(value: Any) -> str:
    if not value:
        return ""
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return f"{d.day} {d:%b %Y}, {d:%H:%M} UTC"
    except ValueError:
        return str(value)


def _short(value: Any, head: int = 8, tail: int = 6) -> str:
    text = str(value or "")
    return text if len(text) <= head + tail + 1 else f"{text[:head]}…{text[-tail:]}"


def make_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
    templates.env.filters.update({"fdate": _fmt_date, "fdt": _fmt_dt, "short": _short})
    return templates


def qr_svg(url: str) -> str:
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=1, error_correction=qrcode.constants.ERROR_CORRECT_M)
    buf = io.BytesIO()
    img.save(buf)
    svg = buf.getvalue().decode("utf-8")
    return svg[svg.index("<svg") :]


def render(request: Request, name: str, status_code: int = 200, **context: Any):
    c = ctx(request)
    base = {
        "user": current_user(request),
        "csrf": getattr(request.state, "csrf", ""),
        "flash": read_flash(request),
        "settings": c.settings,
        "ledger": {"name": c.chain.name, "simulated": c.chain.is_simulated},
        "path": request.url.path,
    }
    return c.templates.TemplateResponse(request, name, {**base, **context}, status_code=status_code)
