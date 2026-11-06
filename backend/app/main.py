"""ASGI app factory. Run: uvicorn app.main:app  (from backend/)  or  python3 scripts/serve.py"""
from __future__ import annotations

import logging
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from app import admin, api, content, db, security
from app.config import Settings
from app.llm import call_groq
from app.ml_service import ModelService

CSP = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"


class Guard(BaseHTTPMiddleware):
    """CSRF defence (custom header + Origin check on state-changing API calls) and security headers."""

    async def dispatch(self, request, call_next):
        cfg = request.app.state.cfg
        if request.url.path.startswith("/api") and request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            same = origin == f"{request.url.scheme}://{request.headers.get('host', '')}"
            if request.headers.get("x-requested-with") != "ArthSetu" or (origin and not same and origin not in cfg.allowed_origins):
                return JSONResponse({"error": {"code": "csrf_rejected", "message": "Request rejected.", "details": []}}, status_code=403)
        resp = await call_next(request)
        h = resp.headers
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "same-origin"
        h["Content-Security-Policy"] = CSP
        if request.url.path.startswith("/api"):
            h["Cache-Control"] = "no-store"
        return resp


async def _api_404(request):
    return JSONResponse({"error": {"code": "not_found", "message": "Unknown API route.", "details": []}}, status_code=404)


def create_app(settings: Settings | None = None) -> Starlette:
    cfg = settings or Settings.from_env()
    logging.basicConfig(level=logging.INFO)
    applied = db.migrate(cfg.db_path)
    svc = ModelService(cfg.models_dir)
    if svc.loaded:
        with db.connect(cfg.db_path) as c:
            new = c.execute("INSERT OR IGNORE INTO model_versions(version,dataset_version,algorithm,metrics_json,first_loaded_at) VALUES(?,?,?,?,?)",
                            (svc.version, svc.meta["dataset_version"], svc.meta["algorithm"], __import__("json").dumps(svc.meta["test"]), db.iso())).rowcount
        if new:
            db.audit(cfg.db_path, "model.deployed", "success", entity=("model", svc.version), meta={"dataset_version": svc.meta["dataset_version"], "algorithm": svc.meta["algorithm"]})
    routes = [*api.routes, *admin.routes, Route("/api/{rest:path}", _api_404)]
    if cfg.frontend_dir and Path(cfg.frontend_dir).is_dir():
        routes.append(Mount("/", StaticFiles(directory=cfg.frontend_dir, html=True)))
    mw = []
    if cfg.allowed_origins:
        mw.append(Middleware(CORSMiddleware, allow_origins=cfg.allowed_origins, allow_credentials=True,
                             allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["content-type", "x-requested-with"]))
    mw.append(Middleware(Guard))
    app = Starlette(routes=routes, middleware=mw)
    app.state.cfg, app.state.model = cfg, svc
    app.state.limiter = security.RateLimiter(cfg.rate_limits_enabled)
    app.state.kb = content.build_kb(svc.meta if svc.loaded else None)
    app.state.llm = lambda messages: call_groq(messages, cfg.groq_api_key, cfg.groq_model, cfg.groq_url)
    app.state.migrations_applied = applied
    return app
