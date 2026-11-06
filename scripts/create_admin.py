"""Create (or promote) the first administrator from the server command line.
Usage: ARTHSETU_ADMIN_PASSWORD='...' python3 scripts/create_admin.py --email you@example.com --name "Your Name"
If the env var is unset you are prompted (input hidden). The password is never printed or logged."""
import argparse, getpass, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from app.bootstrap import create_admin  # noqa: E402
from app.config import Settings  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--email", required=True)
ap.add_argument("--name", default="Administrator")
a = ap.parse_args()
pw = os.environ.get("ARTHSETU_ADMIN_PASSWORD") or getpass.getpass("Admin password (min 10 chars, letters+digits): ")
cfg = Settings.from_env()
try:
    print("Admin", create_admin(cfg.db_path, a.email, a.name, pw, cfg.scrypt_n), "->", a.email)
except ValueError as e:
    sys.exit(f"Error: {e}")
