"""Application factory."""
from __future__ import annotations

import logging
import secrets
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .auth import LocalAuth, SupabaseAuth
from .chain import EvmChain, MockChain
from .config import Settings, get_settings
from .deps import (
    AT_COOKIE,
    FLASH_COOKIE,
    RT_COOKIE,
    SESSION_MAX_AGE,
    AppContext,
    NotApproved,
    Redirect,
    make_templates,
    redirect,
    render,
)
from .routes import account, admin, public
from .security import CSRF_COOKIE, SECURITY_HEADERS, RateLimiter
from .service import Service
from .store import MemoryStore, SupabaseStore

log = logging.getLogger("truemark")
APP_DIR = Path(__file__).resolve().parent


def build_store(settings: Settings):
    if settings.use_supabase:
        return SupabaseStore(settings.supabase_url, settings.supabase_secret_key)
    return MemoryStore()


def build_auth(settings: Settings):
    if settings.use_supabase:
        return SupabaseAuth(settings.supabase_url, settings.supabase_publishable_key, settings.supabase_secret_key)
    return LocalAuth()


def build_chain(settings: Settings, store):
    if settings.chain_mode == "evm":
        return EvmChain(
            rpc_url=settings.rpc_url,
            contract_address=settings.contract_address,
            private_key=settings.issuer_private_key,
            chain_id=settings.chain_id or None,
            chain_name=settings.chain_name,
            explorer_tx_url=settings.explorer_tx_url,
            explorer_address_url=settings.explorer_address_url,
        )
    return MockChain(store)


def create_app(settings: Optional[Settings] = None, *, store=None, auth=None, chain=None) -> FastAPI:
    settings = settings or get_settings()
    store = store or build_store(settings)
    auth = auth or build_auth(settings)
    chain = chain or build_chain(settings, store)
    for problem in settings.problems():
        log.warning("config: %s", problem)

    app = FastAPI(title="TrueMark", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.ctx = AppContext(settings, store, chain, auth, Service(store, chain), RateLimiter(), make_templates())
    app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

    @app.middleware("http")
    async def session_and_security(request: Request, call_next):
        token = request.cookies.get(CSRF_COOKIE)
        fresh_csrf = not token
        request.state.csrf = token or secrets.token_urlsafe(24)
        response = await call_next(request)
        secure = settings.cookie_secure
        if fresh_csrf:
            response.set_cookie(CSRF_COOKIE, request.state.csrf, httponly=True, samesite="lax", secure=secure, path="/")
        session = getattr(request.state, "new_session", None)
        if session:
            for name, value in ((AT_COOKIE, session.access_token), (RT_COOKIE, session.refresh_token)):
                response.set_cookie(name, value, max_age=SESSION_MAX_AGE, httponly=True, samesite="lax", secure=secure, path="/")
        if getattr(request.state, "clear_session", False):
            response.delete_cookie(AT_COOKIE, path="/")
            response.delete_cookie(RT_COOKIE, path="/")
        if request.cookies.get(FLASH_COOKIE) and not getattr(request.state, "flash_set", False):
            response.delete_cookie(FLASH_COOKIE, path="/")
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        if request.url.path.startswith(("/dashboard", "/admin", "/records", "/issue", "/login", "/signup")):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(Redirect)
    async def _redirect(request: Request, exc: Redirect):
        return redirect(request, exc.url, exc.flash, exc.kind)

    @app.exception_handler(NotApproved)
    async def _not_approved(request: Request, exc: NotApproved):
        return render(request, "pending.html", status_code=403)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
        titles = {404: "Page not found", 403: "Not allowed", 429: "Slow down a moment", 409: "Not available yet"}
        return render(
            request,
            "error.html",
            status_code=exc.status_code,
            title=titles.get(exc.status_code, "Something went wrong"),
            message=exc.detail if isinstance(exc.detail, str) else "Something went wrong.",
            code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def _crash(request: Request, exc: Exception):
        log.exception("unhandled error on %s", request.url.path)
        if request.url.path.startswith("/api/"):
            return JSONResponse({"error": "Server error"}, status_code=500)
        return render(request, "error.html", status_code=500, title="Something went wrong", message="The error was logged. Try again in a moment.", code=500)

    app.include_router(public.router)
    app.include_router(account.router)
    app.include_router(admin.router)

    if settings.dev_seed and store.kind == "memory":
        from .devseed import seed

        seed(app.state.ctx)
    return app


def app_factory() -> FastAPI:  # for `uvicorn app.main:app_factory --factory`
    return create_app()
