"""Run the API + UI: python3 scripts/serve.py [--host 127.0.0.1] [--port 8000]   (loads .env if present)"""
import argparse, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
env = ROOT / ".env"
if env.exists():
    for line in env.read_text().splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
import uvicorn  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--host", default="127.0.0.1")
ap.add_argument("--port", type=int, default=8000)
a = ap.parse_args()
uvicorn.run("app.main:create_app", factory=True, host=a.host, port=a.port, app_dir=str(ROOT / "backend"))
