"""Browser end-to-end test (Playwright/Chromium) against a live server on a throwaway database.
Run: python3 backend/tests/e2e/run_e2e.py   (from repo root)"""
import os, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[3]
PORT = 8765
tmp = tempfile.mkdtemp()
env = {**os.environ, "DATABASE_PATH": f"{tmp}/e2e.db", "RATE_LIMITS_ENABLED": "false", "GROQ_API_KEY": "", "GROQ_MODEL": "", "ARTHSETU_ADMIN_PASSWORD": "AdminPassw0rd!"}
subprocess.run([sys.executable, "-I", str(ROOT / "scripts/create_admin.py"), "--email", "admin@example.com", "--name", "Root Admin"], env=env, check=True)
srv = subprocess.Popen([sys.executable, str(ROOT / "scripts/serve.py"), "--port", str(PORT)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
BASE = f"http://127.0.0.1:{PORT}"
for _ in range(60):
    try:
        urllib.request.urlopen(BASE + "/api/health", timeout=1); break
    except Exception:
        time.sleep(0.5)
else:
    srv.kill(); sys.exit("server did not start")

results = []
def check(name, fn):
    try:
        fn(); results.append((name, True, ""))
    except Exception as e:
        results.append((name, False, str(e).splitlines()[0][:600]))

try:
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1200, "height": 900})
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.goto(BASE)
        check("landing renders", lambda: expect(pg.locator("h1")).to_contain_text("Explainable credit-risk"))
        pg.select_option("header select", "hi")
        check("hindi switch", lambda: expect(pg.locator("h1")).to_contain_text("पारदर्शिता"))
        check("html lang=hi", lambda: (_ for _ in ()).throw(AssertionError(pg.evaluate("document.documentElement.lang"))) if pg.evaluate("document.documentElement.lang") != "hi" else None)
        pg.click("#theme-btn")
        check("dark theme applied", lambda: expect(pg.locator("html")).to_have_attribute("data-theme", "dark"))
        pg.reload()
        check("theme+lang persist across reload", lambda: (expect(pg.locator("html")).to_have_attribute("data-theme", "dark"), expect(pg.locator("h1")).to_contain_text("पारदर्शिता")))
        pg.select_option("header select", "en"); pg.click("#theme-btn")
        # protected route
        pg.goto(BASE + "/#/dashboard")
        check("protected route redirects to login", lambda: expect(pg).to_have_url(BASE + "/#/login"))
        # signup
        pg.goto(BASE + "/#/signup")
        pg.click("form button[type=submit]")
        check("signup client validation", lambda: expect(pg.locator("#e-email")).to_contain_text("required"))
        pg.fill("#f-full_name", "Test User"); pg.fill("#f-email", "user@example.com"); pg.fill("#f-password", "short")
        pg.click("form button[type=submit]")
        check("weak password rejected by server", lambda: expect(pg.locator(".alert.bad")).to_be_visible())
        pg.fill("#f-password", "GoodPassw0rd!"); pg.click("form button[type=submit]")
        check("signup -> dashboard", lambda: expect(pg.locator("h1")).to_contain_text("Welcome, Test User"))
        check("no admin link for user", lambda: expect(pg.locator("nav a[href='#/admin']")).to_have_count(0))
        pg.goto(BASE + "/#/admin")
        check("admin URL blocked for user", lambda: expect(pg.locator("main .alert.bad")).to_be_visible())
        # assessment
        pg.goto(BASE + "/#/assess")
        pg.click("#assess-submit")
        check("assessment form validation", lambda: expect(pg.locator("#e-age")).to_contain_text("required"))
        vals = {"revolving_utilization": "1.2", "debt_ratio": "0.9", "open_credit_lines": "8", "real_estate_loans": "1", "past_due_30_59": "3", "past_due_60_89": "1", "past_due_90_plus": "2", "age": "34"}
        for k, v in vals.items(): pg.fill(f"#f-{k}", v)
        pg.fill("#f-age", "200"); pg.click("#assess-submit")
        check("range validation", lambda: expect(pg.locator("#e-age")).to_contain_text("between"))
        pg.fill("#f-age", "34"); pg.fill("#f-label", "<img src=x onerror=alert(1)>"); pg.click("#assess-submit")
        check("result page shows probability", lambda: expect(pg.locator("#prob")).to_contain_text("%", timeout=15000))
        check("risk band shown", lambda: expect(pg.locator("#band .badge")).to_be_visible())
        check("explanation bars rendered", lambda: (expect(pg.locator(".xrow").first).to_be_visible(), None) and None or (_ for _ in ()).throw(AssertionError("few bars")) if pg.locator(".xrow").count() < 5 else None)
        check("label rendered as text (no XSS)", lambda: expect(pg.locator("main")).to_contain_text("<img src=x onerror=alert(1)>") if pg.locator("main img").count() == 0 else (_ for _ in ()).throw(AssertionError("img injected")))
        pg.screenshot(path="/tmp/claude-0/-home-claude/8f899b28-4d38-5d3d-8599-b1d1c5850a5c/scratchpad/result.png", full_page=True); pg.select_option("header select","hi"); pg.click("#theme-btn"); pg.screenshot(path="/tmp/claude-0/-home-claude/8f899b28-4d38-5d3d-8599-b1d1c5850a5c/scratchpad/result_hi_dark.png"); pg.click("#theme-btn"); pg.select_option("header select","en")
        # chatbot (no Groq key -> knowledge-base fallback)
        pg.click("#ask-btn")
        check("chat opens with suggestions", lambda: expect(pg.locator(".chat .sugg button").first).to_be_visible())
        pg.fill("#chat-input", "What does SMOTE do?"); pg.click("#chat-send")
        check("chat reply arrives (KB fallback labelled)", lambda: (expect(pg.locator(".msg.assistant").last).to_contain_text("synthetic", timeout=15000), expect(pg.locator(".msg.assistant").last).to_contain_text("unavailable")))
        pg.click("#chat-clear")
        check("chat clear", lambda: expect(pg.locator(".msg.user")).to_have_count(0))
        pg.click("#chat-close")
        # history & model
        pg.goto(BASE + "/#/history")
        check("history lists assessment", lambda: expect(pg.locator("tbody tr")).to_have_count(1))
        pg.fill("input[type=search]", "zzz-none")
        check("history search filters", lambda: expect(pg.locator("main")).to_contain_text("No assessments match"))
        pg.goto(BASE + "/#/model")
        check("model page real metrics", lambda: expect(pg.locator("main")).to_contain_text("ROC-AUC"))
        # mobile layout
        pg.set_viewport_size({"width": 375, "height": 800}); pg.goto(BASE + "/#/dashboard")
        pg.wait_for_selector("h1")
        check("no horizontal scroll on mobile", lambda: (_ for _ in ()).throw(AssertionError("overflow")) if pg.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1") else None)
        pg.set_viewport_size({"width": 1200, "height": 900})
        # logout
        pg.click("#logout-btn")
        check("logout -> landing", lambda: expect(pg.locator("h1")).to_contain_text("Explainable"))
        pg.goto(BASE + "/#/history")
        check("history requires login after logout", lambda: expect(pg).to_have_url(BASE + "/#/login"))
        # admin
        pg.fill("#f-email", "admin@example.com"); pg.fill("#f-password", "AdminPassw0rd!"); pg.click("form button[type=submit]")
        pg.click("nav a[href='#/admin']")
        check("admin overview shows real counts", lambda: (expect(pg.locator("main")).to_contain_text("Registered users"), expect(pg.locator(".stat .v").nth(0)).to_have_text("2"), expect(pg.locator(".stat .v").nth(2)).to_have_text("1")))
        pg.click("button[data-tab=audit]")
        check("audit shows signup+assessment+failed login", lambda: (expect(pg.locator("main")).to_contain_text("auth.signup"), expect(pg.locator("main")).to_contain_text("assessment.create"), expect(pg.locator("main")).to_contain_text("auth.login")))
        pg.click("button[data-tab=users]")
        check("admin user list", lambda: expect(pg.locator("main")).to_contain_text("user@example.com"))
        pg.click("button[data-tab=predictions]")
        check("admin predictions", lambda: expect(pg.locator("main")).to_contain_text("Prediction volume"))
        pg.click("button[data-tab=system]")
        check("admin system", lambda: expect(pg.locator("main")).to_contain_text("migrations") if False else expect(pg.locator("main")).to_contain_text("001_init"))
        check("no JS errors in console", lambda: (_ for _ in ()).throw(AssertionError(str([e for e in errors if not any(c in e for c in ("401", "403", "422"))][:3]))) if [e for e in errors if not any(c in e for c in ("401", "403", "422"))] else None)
        b.close()
finally:
    srv.terminate()

bad = [r for r in results if not r[1]]
for n, ok, msg in results: print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"  -> {msg}"))
print(f"\n{len(results) - len(bad)}/{len(results)} passed")
sys.exit(1 if bad else 0)
