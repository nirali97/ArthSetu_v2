"""User-facing API: auth, preferences, assessments, history/export, dashboard, model info, chat."""
from __future__ import annotations

import csv
import functools
import io
import json
import logging
import sqlite3
from datetime import timedelta

from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from app import content, db, security
from app.llm import LLMError, SYSTEM
from app.schemas import AssessmentIn, ChatIn, LoginIn, PrefsIn, SignupIn

log = logging.getLogger("arthsetu")
COOKIE = "arthsetu_session"
_DUMMY_HASH = security.hash_password("dummy-password-for-timing", n=2 ** 12)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details=None):
        self.status, self.code, self.message, self.details = status, code, message, details or []


def endpoint(fn):
    @functools.wraps(fn)
    async def wrapper(request: Request):
        try:
            return await fn(request)
        except ApiError as e:
            return JSONResponse({"error": {"code": e.code, "message": e.message, "details": e.details}}, status_code=e.status)
        except Exception:  # never leak internals to the client
            log.exception("unhandled error on %s %s", request.method, request.url.path)
            return JSONResponse({"error": {"code": "internal_error", "message": "Something went wrong. Please try again.", "details": []}}, status_code=500)
    return wrapper


def ip_of(request: Request) -> str | None:
    if request.app.state.cfg.trusted_proxy and request.headers.get("x-forwarded-for"):
        return request.headers["x-forwarded-for"].split(",")[0].strip()
    return request.client.host if request.client else None


def limit(request: Request, key: str, n: int, window: float = 60.0):
    if not request.app.state.limiter.allow(key, n, window):
        raise ApiError(429, "rate_limited", "Too many requests. Please wait a moment and try again.")


async def parse(request: Request, model):
    try:
        data = await request.json()
    except Exception:
        raise ApiError(400, "invalid_json", "Request body must be valid JSON.")
    try:
        return model.model_validate(data)
    except ValidationError as e:
        raise ApiError(422, "validation_error", "Some fields are invalid.",
                       [{"field": ".".join(str(x) for x in err["loc"]), "message": err["msg"].removeprefix("Value error, ")} for err in e.errors()])


def current_user(request: Request, admin: bool = False) -> dict:
    cfg = request.app.state.cfg
    tok = request.cookies.get(COOKIE)
    if not tok:
        raise ApiError(401, "unauthenticated", "Please sign in.")
    with db.connect(cfg.db_path) as c:
        r = c.execute("SELECT s.id sid, s.expires_at, s.last_seen_at, u.id, u.email, u.full_name, u.role, u.is_active "
                      "FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.id=?", (security.token_hash(tok),)).fetchone()
        if not r:
            raise ApiError(401, "unauthenticated", "Please sign in.")
        t = db.now()
        if t > db.parse(r["expires_at"]) or t - db.parse(r["last_seen_at"]) > timedelta(minutes=cfg.idle_timeout_minutes) or not r["is_active"]:
            c.execute("DELETE FROM sessions WHERE id=?", (r["sid"],))
            raise ApiError(401, "session_expired", "Your session has expired. Please sign in again.")
        c.execute("UPDATE sessions SET last_seen_at=? WHERE id=?", (db.iso(), r["sid"]))
    user = {k: r[k] for k in ("id", "email", "full_name", "role")}
    if admin and user["role"] != "ADMIN":
        db.audit(cfg.db_path, "authz.denied", "failure", user, ("route", request.url.path), ip_of(request))
        raise ApiError(403, "forbidden", "Administrator access is required.")
    return user


def _start_session(request: Request, user_id: int) -> tuple[str, str]:
    cfg = request.app.state.cfg
    token, h = security.new_token()
    with db.connect(cfg.db_path) as c:
        c.execute("INSERT INTO sessions(id,user_id,created_at,expires_at,last_seen_at,ip,user_agent) VALUES(?,?,?,?,?,?,?)",
                  (h, user_id, db.iso(), db.iso(db.now() + timedelta(hours=cfg.session_ttl_hours)), db.iso(), ip_of(request),
                   (request.headers.get("user-agent") or "")[:200]))
    return token, h


def _set_cookie(request: Request, resp: Response, token: str):
    cfg = request.app.state.cfg
    resp.set_cookie(COOKIE, token, max_age=int(cfg.session_ttl_hours * 3600), httponly=True, secure=cfg.cookie_secure, samesite="lax", path="/")


def _profile(cfg, uid: int) -> dict:
    with db.connect(cfg.db_path) as c:
        u = c.execute("SELECT id,email,full_name,role,created_at,last_login_at FROM users WHERE id=?", (uid,)).fetchone()
        p = c.execute("SELECT theme,language FROM user_preferences WHERE user_id=?", (uid,)).fetchone()
    return {**dict(u), "preferences": dict(p) if p else {"theme": "light", "language": "en"}}


# ---------------------------------------------------------------- auth
@endpoint
async def signup(request: Request):
    cfg = request.app.state.cfg
    ip = ip_of(request)
    limit(request, f"signup:{ip}", 5)
    d = await parse(request, SignupIn)
    prob = security.password_problem(d.password, d.email)
    if prob:
        raise ApiError(422, "weak_password", prob, [{"field": "password", "message": prob}])
    pw_hash = await run_in_threadpool(security.hash_password, d.password, cfg.scrypt_n)
    try:
        with db.connect(cfg.db_path) as c:
            cur = c.execute("INSERT INTO users(email,full_name,password_hash,role,created_at,last_login_at) VALUES(?,?,?,'USER',?,?)",
                            (d.email, d.full_name, pw_hash, db.iso(), db.iso()))
            uid = cur.lastrowid
            c.execute("INSERT INTO user_preferences(user_id) VALUES(?)", (uid,))
    except sqlite3.IntegrityError:
        db.audit(cfg.db_path, "auth.signup", "failure", ip=ip, meta={"reason": "email_taken"}, actor_email=d.email)
        raise ApiError(409, "email_taken", "An account with this email already exists.", [{"field": "email", "message": "Already registered."}])
    token, _ = _start_session(request, uid)
    db.audit(cfg.db_path, "auth.signup", "success", {"id": uid, "email": d.email}, ("user", uid), ip)
    resp = JSONResponse({"user": _profile(cfg, uid)}, status_code=201)
    _set_cookie(request, resp, token)
    return resp


@endpoint
async def login(request: Request):
    cfg = request.app.state.cfg
    ip = ip_of(request)
    limit(request, f"login:{ip}", 10)
    d = await parse(request, LoginIn)
    email = d.email.strip().lower()
    with db.connect(cfg.db_path) as c:
        u = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if u and u["locked_until"] and db.now() < db.parse(u["locked_until"]):
        db.audit(cfg.db_path, "auth.login", "failure", {"id": u["id"], "email": email}, ("user", u["id"]), ip, {"reason": "locked"})
        raise ApiError(429, "account_locked", "Too many failed attempts. Try again in a few minutes.")
    good = await run_in_threadpool(security.verify_password, d.password, u["password_hash"] if u else _DUMMY_HASH)
    if not u or not good or not u["is_active"]:
        reason = "unknown_user" if not u else "inactive" if good and not u["is_active"] else "bad_password"
        if u:
            fails = u["failed_logins"] + 1
            with db.connect(cfg.db_path) as c:
                if fails >= 5:
                    c.execute("UPDATE users SET failed_logins=0, locked_until=? WHERE id=?", (db.iso(db.now() + timedelta(minutes=15)), u["id"]))
                else:
                    c.execute("UPDATE users SET failed_logins=? WHERE id=?", (fails, u["id"]))
        db.audit(cfg.db_path, "auth.login", "failure", {"id": u["id"], "email": email} if u else None, ("user", u["id"]) if u else None,
                 ip, {"reason": reason}, actor_email=email)
        raise ApiError(401, "invalid_credentials", "Incorrect email or password.")
    with db.connect(cfg.db_path) as c:
        c.execute("UPDATE users SET failed_logins=0, locked_until=NULL, last_login_at=? WHERE id=?", (db.iso(), u["id"]))
    token, _ = _start_session(request, u["id"])
    db.audit(cfg.db_path, "auth.login", "success", {"id": u["id"], "email": email}, ("user", u["id"]), ip)
    resp = JSONResponse({"user": _profile(cfg, u["id"])})
    _set_cookie(request, resp, token)
    return resp


@endpoint
async def logout(request: Request):
    cfg = request.app.state.cfg
    tok = request.cookies.get(COOKIE)
    actor = None
    if tok:
        with db.connect(cfg.db_path) as c:
            r = c.execute("SELECT u.id,u.email FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.id=?", (security.token_hash(tok),)).fetchone()
            c.execute("DELETE FROM sessions WHERE id=?", (security.token_hash(tok),))
        actor = dict(r) if r else None
    if actor:
        db.audit(cfg.db_path, "auth.logout", "success", actor, ("user", actor["id"]), ip_of(request))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp


@endpoint
async def me(request: Request):
    u = current_user(request)
    return JSONResponse({"user": _profile(request.app.state.cfg, u["id"])})


@endpoint
async def patch_prefs(request: Request):
    u = current_user(request)
    d = await parse(request, PrefsIn)
    with db.connect(request.app.state.cfg.db_path) as c:
        if d.theme:
            c.execute("UPDATE user_preferences SET theme=? WHERE user_id=?", (d.theme, u["id"]))
        if d.language:
            c.execute("UPDATE user_preferences SET language=? WHERE user_id=?", (d.language, u["id"]))
    return JSONResponse({"preferences": _profile(request.app.state.cfg, u["id"])["preferences"]})


# ---------------------------------------------------------------- assessments
def _row_to_result(r, with_detail: bool = True) -> dict:
    out = {"id": r["id"], "label": r["label"], "created_at": r["created_at"], "probability": r["probability"], "risk_band": r["risk_band"],
           "model_version": r["model_version"], "threshold": r["threshold"]}
    if with_detail:
        out["inputs"] = json.loads(r["inputs_json"])
        out["explanation"] = json.loads(r["explanation_json"])
    return out


_SELECT = ("SELECT a.id,a.label,a.created_at,a.inputs_json,p.probability,p.risk_band,p.model_version,p.threshold,p.explanation_json "
           "FROM assessments a JOIN prediction_results p ON p.assessment_id=a.id ")


@endpoint
async def create_assessment(request: Request):
    cfg, svc = request.app.state.cfg, request.app.state.model
    u = current_user(request)
    limit(request, f"assess:{u['id']}", 30)
    d = await parse(request, AssessmentIn)
    inputs = d.model_dump(exclude={"label"})
    if not svc.loaded:
        db.audit(cfg.db_path, "assessment.create", "failure", u, ip=ip_of(request), meta={"reason": "model_unavailable"})
        raise ApiError(503, "model_unavailable", "The prediction model is not available right now.")
    try:
        res = await run_in_threadpool(svc.predict, inputs)
    except Exception:
        log.exception("prediction failed")
        db.audit(cfg.db_path, "assessment.create", "failure", u, ip=ip_of(request), meta={"reason": "prediction_error"})
        raise ApiError(500, "prediction_failed", "The assessment could not be completed. Please check your inputs and try again.")
    ts = db.iso()
    with db.connect(cfg.db_path) as c:
        aid = c.execute("INSERT INTO assessments(user_id,label,inputs_json,created_at) VALUES(?,?,?,?)", (u["id"], d.label, json.dumps(inputs), ts)).lastrowid
        c.execute("INSERT INTO prediction_results(assessment_id,model_version,probability,risk_band,threshold,explanation_json,created_at) VALUES(?,?,?,?,?,?,?)",
                  (aid, res["model_version"], res["probability"], res["risk_band"], res["threshold"], json.dumps(res["explanation"]), ts))
    db.audit(cfg.db_path, "assessment.create", "success", u, ("assessment", aid), ip_of(request),
             {"model_version": res["model_version"], "risk_band": res["risk_band"]})   # no financial inputs in audit
    return JSONResponse({"id": aid, "label": d.label, "created_at": ts, "inputs": inputs, **res}, status_code=201)


@endpoint
async def list_assessments(request: Request):
    u = current_user(request)
    q = request.query_params
    page, size = max(int(q.get("page", 1) or 1), 1), min(max(int(q.get("page_size", 10) or 10), 1), 50)
    where, args = ["a.user_id=?"], [u["id"]]
    if q.get("q"):
        where.append("a.label LIKE ? ESCAPE '\\'")
        args.append("%" + q["q"].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    if q.get("band") in ("LOW", "MODERATE", "HIGH"):
        where.append("p.risk_band=?"); args.append(q["band"])
    w = " WHERE " + " AND ".join(where)
    with db.connect(request.app.state.cfg.db_path) as c:
        total = c.execute("SELECT COUNT(*) FROM assessments a JOIN prediction_results p ON p.assessment_id=a.id" + w, args).fetchone()[0]
        rows = c.execute(_SELECT + w + " ORDER BY a.created_at DESC, a.id DESC LIMIT ? OFFSET ?", args + [size, (page - 1) * size]).fetchall()
    return JSONResponse({"items": [_row_to_result(r, False) for r in rows], "total": total, "page": page, "page_size": size})


@endpoint
async def get_assessment(request: Request):
    u = current_user(request)
    with db.connect(request.app.state.cfg.db_path) as c:
        r = c.execute(_SELECT + "WHERE a.id=? AND a.user_id=?", (request.path_params["id"], u["id"])).fetchone()
    if not r:
        raise ApiError(404, "not_found", "Assessment not found.")   # same answer for "not yours" and "does not exist"
    return JSONResponse(_row_to_result(r))


def _csv_safe(v) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


@endpoint
async def export_assessments(request: Request):
    u = current_user(request)
    with db.connect(request.app.state.cfg.db_path) as c:
        rows = c.execute(_SELECT + "WHERE a.user_id=? ORDER BY a.created_at DESC", (u["id"],)).fetchall()
    cols = ["id", "created_at", "label", "probability_of_default", "risk_band", "model_version"]
    inputs = list(AssessmentIn.model_fields.keys())[1:]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols + inputs)
    for r in rows:
        i = json.loads(r["inputs_json"])
        w.writerow([_csv_safe(x) for x in [r["id"], r["created_at"], r["label"], round(r["probability"], 6), r["risk_band"], r["model_version"]] + [i.get(k) for k in inputs]])
    db.audit(request.app.state.cfg.db_path, "assessment.export", "success", u, ip=ip_of(request), meta={"rows": len(rows)})
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=arthsetu_assessments.csv"})


@endpoint
async def dashboard(request: Request):
    u = current_user(request)
    svc = request.app.state.model
    with db.connect(request.app.state.cfg.db_path) as c:
        total = c.execute("SELECT COUNT(*) FROM assessments WHERE user_id=?", (u["id"],)).fetchone()[0]
        bands = {r[0]: r[1] for r in c.execute("SELECT p.risk_band, COUNT(*) FROM assessments a JOIN prediction_results p ON p.assessment_id=a.id WHERE a.user_id=? GROUP BY 1", (u["id"],))}
        recent = c.execute(_SELECT + "WHERE a.user_id=? ORDER BY a.created_at DESC, a.id DESC LIMIT 5", (u["id"],)).fetchall()
        activity = c.execute("SELECT ts,action,outcome FROM audit_logs WHERE actor_user_id=? AND action IN ('auth.login','assessment.create','assessment.export') ORDER BY ts DESC LIMIT 5", (u["id"],)).fetchall()
    return JSONResponse({"total_assessments": total, "band_counts": bands, "recent": [_row_to_result(r, False) for r in recent],
                         "activity": [dict(a) for a in activity], "model_version": svc.version if svc.loaded else None})


# ---------------------------------------------------------------- model & content
@endpoint
async def model_info(request: Request):
    current_user(request)
    svc = request.app.state.model
    if not svc.loaded:
        raise ApiError(503, "model_unavailable", "Model not loaded.")
    m = svc.meta
    return JSONResponse({k: m[k] for k in ["model_version", "dataset_version", "trained_utc", "random_seed", "split_policy", "algorithm", "resampling",
                                          "xgboost_smote_status", "cv_5fold_train_oof", "cv_oof_calibrated_at_threshold", "train_in_sample", "test",
                                          "risk_bands", "global_importance", "reliability_test_deciles", "base_rate_train", "decision_threshold_rule", "features"]}
                        | {"library_versions": m["library_versions"], "features_info": content.feature_payload(),
                           "limitations": ["Trained on US consumer credit data (2011), not Indian borrowers or MSMEs.",
                                           "No timestamps: the 90-days-late count may leak information close to the target.",
                                           "Age is an input feature (fairness concern).",
                                           "Outputs are statistical decision-support estimates, not loan approvals."]})


@endpoint
async def features_info(request: Request):
    return JSONResponse(content.feature_payload())


@endpoint
async def health(request: Request):
    cfg = request.app.state.cfg
    try:
        with db.connect(cfg.db_path) as c:
            c.execute("SELECT 1").fetchone()
        dbs = "ok"
    except Exception:
        dbs = "error"
    return JSONResponse({"status": "ok" if dbs == "ok" and request.app.state.model.loaded else "degraded", "database": dbs,
                         "model_loaded": request.app.state.model.loaded})


# ---------------------------------------------------------------- chat
@endpoint
async def chat(request: Request):
    cfg, st = request.app.state.cfg, request.app.state
    u = current_user(request)
    limit(request, f"chat:{u['id']}", 20)
    d = await parse(request, ChatIn)
    lang = d.language
    factors = [f for f in d.top_factors if f in content.FEATURES]           # whitelist: nothing free-form reaches the prompt
    with db.connect(cfg.db_path) as c:
        if d.session_id:
            s = c.execute("SELECT id FROM chat_sessions WHERE id=? AND user_id=?", (d.session_id, u["id"])).fetchone()
            if not s:
                raise ApiError(404, "not_found", "Chat session not found.")
            sid = s["id"]
        else:
            sid = c.execute("INSERT INTO chat_sessions(user_id,created_at) VALUES(?,?)", (u["id"], db.iso())).lastrowid
        hist = [dict(r) for r in c.execute("SELECT role,content FROM chat_messages WHERE session_id=? ORDER BY id DESC LIMIT 6", (sid,))][::-1]
        c.execute("INSERT INTO chat_messages(session_id,role,content,created_at) VALUES(?,?,?,?)", (sid, "user", d.message, db.iso()))
    hits = content.retrieve(st.kb, d.message + " " + " ".join(factors)) or [e for e in st.kb if e["id"] in ("platform", "limits")]
    ctx = "\n".join(f"- {e[lang]}" for e in hits)
    extra = ""
    if d.risk_band:
        extra = f"\nThe user is viewing a result in risk band {d.risk_band}" + (f"; top factors: {', '.join(content.FEATURES[f][0] for f in factors)}" if factors else "") + "."
    sys_msg = f"{SYSTEM}\nLanguage: {'Hindi' if lang == 'hi' else 'English'}.\nPage: {content.PAGE_HINTS.get(d.page, '')}{extra}\nCONTEXT:\n{ctx}"
    msgs = [{"role": "system", "content": sys_msg}] + hist + [{"role": "user", "content": d.message}]
    mode, warning = "groq", None
    try:
        reply = await run_in_threadpool(st.llm, msgs)
        if not reply:
            raise LLMError("empty")
    except LLMError as e:
        mode, warning = "knowledge_base_only", str(e)
        head = "AI assistant is unavailable right now; here is what the ArthSetu knowledge base says:\n" if lang == "en" else "AI सहायक अभी उपलब्ध नहीं है; ArthSetu ज्ञान-आधार के अनुसार:\n"
        reply = head + "\n".join(f"• {e2[lang]}" for e2 in hits[:2])
    with db.connect(cfg.db_path) as c:
        c.execute("INSERT INTO chat_messages(session_id,role,content,created_at) VALUES(?,?,?,?)", (sid, "assistant", reply, db.iso()))
    db.audit(cfg.db_path, "chat.message", "success" if mode == "groq" else "failure", u, ("chat_session", sid), ip_of(request),
             {"mode": mode, "warning": warning, "page": d.page})
    return JSONResponse({"session_id": sid, "reply": reply, "mode": mode, "warning": warning})


@endpoint
async def chat_history(request: Request):
    u = current_user(request)
    sid = request.query_params.get("session_id")
    with db.connect(request.app.state.cfg.db_path) as c:
        if not sid:
            s = c.execute("SELECT id FROM chat_sessions WHERE user_id=? ORDER BY id DESC LIMIT 1", (u["id"],)).fetchone()
            sid = s["id"] if s else None
        elif not c.execute("SELECT 1 FROM chat_sessions WHERE id=? AND user_id=?", (sid, u["id"])).fetchone():
            raise ApiError(404, "not_found", "Chat session not found.")
        msgs = [dict(r) for r in c.execute("SELECT role,content,created_at FROM chat_messages WHERE session_id=? ORDER BY id", (sid,))] if sid else []
    return JSONResponse({"session_id": sid, "messages": msgs})


@endpoint
async def chat_clear(request: Request):
    u = current_user(request)
    with db.connect(request.app.state.cfg.db_path) as c:
        c.execute("DELETE FROM chat_sessions WHERE id=? AND user_id=?", (request.path_params["id"], u["id"]))
    return JSONResponse({"ok": True})


routes = [
    Route("/api/health", health), Route("/api/features", features_info),
    Route("/api/auth/signup", signup, methods=["POST"]), Route("/api/auth/login", login, methods=["POST"]),
    Route("/api/auth/logout", logout, methods=["POST"]), Route("/api/auth/me", me),
    Route("/api/me/preferences", patch_prefs, methods=["PATCH"]),
    Route("/api/assessments", create_assessment, methods=["POST"]), Route("/api/assessments", list_assessments, methods=["GET"]),
    Route("/api/assessments/export.csv", export_assessments), Route("/api/assessments/{id:int}", get_assessment),
    Route("/api/dashboard", dashboard), Route("/api/model", model_info),
    Route("/api/chat", chat, methods=["POST"]), Route("/api/chat/history", chat_history), Route("/api/chat/{id:int}", chat_clear, methods=["DELETE"]),
]
