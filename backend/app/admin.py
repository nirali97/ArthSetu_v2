"""Administrator API. Every handler re-checks the ADMIN role server-side from the session (never from the client)."""
from __future__ import annotations

import json
import time

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from app import db
from app.api import ApiError, current_user, endpoint, ip_of, parse
from app.schemas import AdminUserPatch

STARTED = time.time()


def _page(request: Request, default: int = 20):
    q = request.query_params
    page, size = max(int(q.get("page", 1) or 1), 1), min(max(int(q.get("page_size", default) or default), 1), 100)
    return page, size, (page - 1) * size


def _like(s: str) -> str:
    return "%" + s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


@endpoint
async def overview(request: Request):
    current_user(request, admin=True)
    cfg, svc = request.app.state.cfg, request.app.state.model
    since24 = db.iso(db.now() - __import__("datetime").timedelta(hours=24))
    since14 = db.iso(db.now() - __import__("datetime").timedelta(days=14))
    with db.connect(cfg.db_path) as c:
        one = lambda sql, a=(): c.execute(sql, a).fetchone()[0]  # noqa: E731
        data = {
            "total_users": one("SELECT COUNT(*) FROM users"),
            "active_users_24h": one("SELECT COUNT(DISTINCT user_id) FROM sessions WHERE last_seen_at>=?", (since24,)),
            "total_assessments": one("SELECT COUNT(*) FROM assessments"),
            "assessments_per_day": [dict(r) for r in c.execute("SELECT substr(created_at,1,10) day, COUNT(*) n FROM assessments WHERE created_at>=? GROUP BY 1 ORDER BY 1", (since14,))],
            "model_usage": [dict(r) for r in c.execute("SELECT model_version, COUNT(*) n FROM prediction_results GROUP BY 1 ORDER BY 2 DESC")],
        }
    data["system"] = {"database": "ok", "model_loaded": svc.loaded, "model_version": svc.version if svc.loaded else None,
                      "assistant_configured": bool(cfg.groq_api_key and cfg.groq_model), "uptime_seconds": int(time.time() - STARTED)}
    return JSONResponse(data)


@endpoint
async def users(request: Request):
    current_user(request, admin=True)
    page, size, off = _page(request)
    q = request.query_params.get("q", "").strip()
    where, args = ("WHERE u.email LIKE ? ESCAPE '\\' OR u.full_name LIKE ? ESCAPE '\\'", [_like(q)] * 2) if q else ("", [])
    with db.connect(request.app.state.cfg.db_path) as c:
        total = c.execute(f"SELECT COUNT(*) FROM users u {where}", args).fetchone()[0]
        rows = c.execute(f"SELECT u.id,u.email,u.full_name,u.role,u.is_active,u.created_at,u.last_login_at,"
                         f"(SELECT COUNT(*) FROM assessments a WHERE a.user_id=u.id) assessments FROM users u {where} ORDER BY u.id LIMIT ? OFFSET ?",
                         args + [size, off]).fetchall()
    return JSONResponse({"items": [dict(r) | {"is_active": bool(r["is_active"])} for r in rows], "total": total, "page": page, "page_size": size})


@endpoint
async def patch_user(request: Request):
    admin = current_user(request, admin=True)
    cfg = request.app.state.cfg
    uid = request.path_params["id"]
    d = await parse(request, AdminUserPatch)
    if uid == admin["id"]:
        raise ApiError(400, "self_change", "You cannot change your own role or status.")
    changes = {k: v for k, v in d.model_dump().items() if v is not None}
    if not changes:
        raise ApiError(422, "validation_error", "Nothing to change.")
    with db.connect(cfg.db_path) as c:
        t = c.execute("SELECT id,email,role,is_active FROM users WHERE id=?", (uid,)).fetchone()
        if not t:
            raise ApiError(404, "not_found", "User not found.")
        if "role" in changes:
            c.execute("UPDATE users SET role=? WHERE id=?", (changes["role"], uid))
        if "is_active" in changes:
            c.execute("UPDATE users SET is_active=? WHERE id=?", (int(changes["is_active"]), uid))
            if not changes["is_active"]:
                c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))   # revoke access immediately
    db.audit(cfg.db_path, "admin.user.update", "success", admin, ("user", uid), ip_of(request),
             {"target_email": t["email"], "from": {"role": t["role"], "is_active": bool(t["is_active"])}, "to": changes})
    return JSONResponse({"ok": True, "id": uid, **changes})


@endpoint
async def audit_logs(request: Request):
    current_user(request, admin=True)
    page, size, off = _page(request, 25)
    qp = request.query_params
    where, args = [], []
    if qp.get("action"):
        where.append("action LIKE ? ESCAPE '\\'"); args.append(_like(qp["action"]))
    if qp.get("outcome") in ("success", "failure"):
        where.append("outcome=?"); args.append(qp["outcome"])
    if qp.get("actor"):
        where.append("actor_email LIKE ? ESCAPE '\\'"); args.append(_like(qp["actor"]))
    w = (" WHERE " + " AND ".join(where)) if where else ""
    with db.connect(request.app.state.cfg.db_path) as c:
        total = c.execute("SELECT COUNT(*) FROM audit_logs" + w, args).fetchone()[0]
        rows = c.execute("SELECT * FROM audit_logs" + w + " ORDER BY ts DESC, rowid DESC LIMIT ? OFFSET ?", args + [size, off]).fetchall()
    items = [{"id": r["id"], "timestamp": r["ts"], "actor": r["actor_email"], "actor_user_id": r["actor_user_id"], "action": r["action"],
              "entity": f"{r['entity_type']}:{r['entity_id']}" if r["entity_type"] else None, "outcome": r["outcome"], "ip": r["ip"],
              "metadata": json.loads(r["metadata_json"])} for r in rows]
    return JSONResponse({"items": items, "total": total, "page": page, "page_size": size})


@endpoint
async def predictions(request: Request):
    current_user(request, admin=True)
    since = db.iso(db.now() - __import__("datetime").timedelta(days=30))
    with db.connect(request.app.state.cfg.db_path) as c:
        out = {
            "volume_per_day": [dict(r) for r in c.execute("SELECT substr(created_at,1,10) day, COUNT(*) n FROM prediction_results WHERE created_at>=? GROUP BY 1 ORDER BY 1", (since,))],
            "band_distribution": {r[0]: r[1] for r in c.execute("SELECT risk_band, COUNT(*) FROM prediction_results GROUP BY 1")},
            "model_versions": [dict(r) for r in c.execute("SELECT model_version, COUNT(*) n, MIN(created_at) first_used, MAX(created_at) last_used FROM prediction_results GROUP BY 1")],
            "failed_requests_total": c.execute("SELECT COUNT(*) FROM audit_logs WHERE action='assessment.create' AND outcome='failure'").fetchone()[0],
            "recent_failures": [{"timestamp": r["ts"], "actor": r["actor_email"], "reason": json.loads(r["metadata_json"]).get("reason")}
                                for r in c.execute("SELECT ts,actor_email,metadata_json FROM audit_logs WHERE action='assessment.create' AND outcome='failure' ORDER BY ts DESC LIMIT 10")],
        }
    return JSONResponse(out)


@endpoint
async def system(request: Request):
    current_user(request, admin=True)
    st, cfg = request.app.state, request.app.state.cfg
    with db.connect(cfg.db_path) as c:
        mig = [r[0] for r in c.execute("SELECT name FROM schema_migrations ORDER BY name")]
    return JSONResponse({"database": "ok", "migrations": mig, "model_loaded": st.model.loaded, "model_version": st.model.version if st.model.loaded else None,
                         "assistant_configured": bool(cfg.groq_api_key and cfg.groq_model), "cookie_secure": cfg.cookie_secure,
                         "rate_limits_enabled": cfg.rate_limits_enabled, "uptime_seconds": int(time.time() - STARTED)})


routes = [Route("/api/admin/overview", overview), Route("/api/admin/users", users), Route("/api/admin/users/{id:int}", patch_user, methods=["PATCH"]),
          Route("/api/admin/audit", audit_logs), Route("/api/admin/predictions", predictions), Route("/api/admin/system", system)]
