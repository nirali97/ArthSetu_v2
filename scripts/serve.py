
"""Run the API + UI: python3 scripts/serve.py [--host HOST] [--port PORT]
Loads .env if present.
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

# Load local .env if present. Render environment variables take priority.
env = ROOT / ".env"
if env.exists():
    for line in env.read_text().splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(
                k.strip(),
                v.strip().strip('"').strip("'")
            )

import uvicorn  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument(
    "--host",
    default=os.environ.get("HOST", "0.0.0.0")
)
ap.add_argument(
    "--port",
    type=int,
    default=int(os.environ.get("PORT", "8000"))
)
a = ap.parse_args()

uvicorn.run(
    "app.main:create_app",
    factory=True,
    host=a.host,
    port=a.port,
    app_dir=str(ROOT / "backend")
)
