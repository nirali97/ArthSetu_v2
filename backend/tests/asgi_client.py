"""Tiny in-process ASGI client with a cookie jar (httpx is not installed in the build environment)."""
import asyncio, json as _json
from urllib.parse import urlsplit


class Resp:
    def __init__(self, status, headers, body):
        self.status, self.headers, self.body = status, headers, body

    def json(self):
        return _json.loads(self.body or b"null")

    @property
    def text(self):
        return self.body.decode()


class Client:
    def __init__(self, app, ip="127.0.0.1"):
        self.app, self.cookies, self.ip = app, {}, ip

    def request(self, method, path, json=None, headers=None, csrf=True, raw=None):
        u = urlsplit(path)
        body = raw if raw is not None else (_json.dumps(json).encode() if json is not None else b"")
        h = {"host": "testserver", "user-agent": "pytest"}
        if json is not None or raw is not None:
            h["content-type"] = "application/json"
        if csrf and method not in ("GET", "HEAD"):
            h["x-requested-with"] = "ArthSetu"
        h.update({k.lower(): v for k, v in (headers or {}).items()})
        if self.cookies:
            h["cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http", "path": u.path,
                 "raw_path": u.path.encode(), "query_string": u.query.encode(), "root_path": "", "client": (self.ip, 5000), "server": ("testserver", 80),
                 "headers": [(k.encode(), v.encode()) for k, v in h.items()]}
        out = {"status": 0, "headers": [], "body": b""}

        async def run():
            sent = False

            async def receive():
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                await asyncio.sleep(3600)

            async def send(msg):
                if msg["type"] == "http.response.start":
                    out["status"], out["headers"] = msg["status"], msg["headers"]
                elif msg["type"] == "http.response.body":
                    out["body"] += msg.get("body", b"")

            await self.app(scope, receive, send)

        asyncio.run(run())
        hdrs = {}
        for k, v in out["headers"]:
            k, v = k.decode().lower(), v.decode()
            if k == "set-cookie":
                name, _, rest = v.partition("=")
                val = rest.split(";")[0]
                hdrs.setdefault("set-cookie", []).append(v)
                if "max-age=0" in v.lower() or val in ('""', ""):
                    self.cookies.pop(name, None)
                else:
                    self.cookies[name] = val
            else:
                hdrs[k] = v
        return Resp(out["status"], hdrs, out["body"])

    def get(self, p, **k): return self.request("GET", p, **k)
    def post(self, p, json=None, **k): return self.request("POST", p, json=json, **k)
    def patch(self, p, json=None, **k): return self.request("PATCH", p, json=json, **k)
    def delete(self, p, **k): return self.request("DELETE", p, **k)
