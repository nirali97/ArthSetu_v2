"""Safe first-administrator creation. Only reachable from the server command line (never over HTTP); no default account exists."""
from __future__ import annotations

from app import db, security


def create_admin(db_path: str, email: str, full_name: str, password: str, scrypt_n: int = 2 ** 15) -> str:
    email = email.strip().lower()
    if not security.EMAIL_RE.match(email):
        raise ValueError("invalid email")
    problem = security.password_problem(password, email)
    if problem:
        raise ValueError(problem)
    db.migrate(db_path)
    h = security.hash_password(password, n=scrypt_n)
    with db.connect(db_path) as c:
        row = c.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if row:
            c.execute("UPDATE users SET role='ADMIN', is_active=1, password_hash=? WHERE id=?", (h, row["id"]))
            uid, action = row["id"], "promoted"
        else:
            uid = c.execute("INSERT INTO users(email,full_name,password_hash,role,created_at) VALUES(?,?,?,'ADMIN',?)", (email, full_name, h, db.iso())).lastrowid
            c.execute("INSERT INTO user_preferences(user_id) VALUES(?)", (uid,))
            action = "created"
    db.audit(db_path, "admin.bootstrap", "success", {"id": uid, "email": email}, ("user", uid), "cli", {"result": action})
    return action
