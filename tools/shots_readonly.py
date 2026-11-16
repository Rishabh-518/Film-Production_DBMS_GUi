import os, sys, subprocess, time, urllib.request
from pathlib import Path
os.environ["APP_DBNAME"] = "film_demo"
APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
from playwright.sync_api import sync_playwright
from db import transaction
from take_screenshots import credentials
OUT = APP_DIR.parent / "Final_Improved" / "Final_Report" / "screenshots"
PORT = 8611; URL = f"http://localhost:{PORT}"
SKIPPED = []; SAVED = []

def query(sql, params=()):
    with transaction() as cur:
        cur.execute(sql, params)
        return cur.fetchall() if cur.description else []
def title_of(i): return query("SELECT title FROM Production WHERE production_id=%s", (i,))[0]["title"]
def settle(p, ms=1000): p.wait_for_timeout(ms)
def shot(p, name):
    OUT.mkdir(parents=True, exist_ok=True); settle(p, 800)
    p.screenshot(path=str(OUT / f"{name}.png"), full_page=True); SAVED.append(name); print("saved", name)
def login(br, who):
    ctx = br.new_context(viewport={"width": 1400, "height": 2000}); p = ctx.new_page()
    p.goto(URL)
    email, password = credentials(who)
    p.get_by_label("Email", exact=True).fill(email)
    p.get_by_label("Password", exact=True).fill(password)
    p.get_by_role("button", name="Log in").click()
    p.get_by_role("heading", name="Home", exact=True).wait_for(timeout=20000)
    settle(p, 1500); return p
def open_production(p, title):
    if p.get_by_role("button", name="Switch production").count():
        p.get_by_role("button", name="Switch production").click(); settle(p, 1500)
    p.get_by_role("tab", name="Productions", exact=True).click(); settle(p)
    p.get_by_label("Search by title", exact=True).fill(title); p.keyboard.press("Enter"); settle(p, 1500)
    g = p.get_by_test_id("stDataFrame").locator("visible=true").first.bounding_box()
    p.mouse.click(g["x"] + 70, g["y"] + 52)
    p.get_by_role("button", name="Switch production").wait_for(timeout=15000); settle(p)
def go(p, name):
    p.locator("[data-testid=stSidebar]").get_by_role("button", name=name, exact=True).click(); settle(p, 1800)
def tab(p, name):
    p.get_by_role("tab", name=name, exact=True).click(); settle(p, 800)
def attempt(name, f):
    for _ in range(2):
        try: f(); return
        except Exception as e: err = str(e).splitlines()[0][:150]
    SKIPPED.append((name, err)); print("SKIPPED", name, err)

def main():
    srv = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", str(PORT),
        "--server.headless", "true", "--browser.gatherUsageStats", "false"], cwd=APP_DIR,
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    try:
        for _ in range(60):
            try:
                if urllib.request.urlopen(f"{URL}/_stcore/health").read() == b"ok": break
            except OSError: time.sleep(1)
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            t1 = title_of(1); t3 = title_of(3)
            n = [0]
            def S(who, label, steps, prod=None):
                def run():
                    p = login(br, who)
                    try:
                        if prod: open_production(p, prod)
                        steps(p)
                    finally: p.context.close()
                attempt(label, run)
            def bud3(p):
                go(p, "Budget and expenses")
                p.get_by_label("Budget version", exact=True).click(); settle(p, 600)
                print([o.inner_text() for o in p.get_by_role("option").all()])
                p.get_by_role("option").filter(has_text="Approved").first.click(); settle(p, 1500)
                shot(p, "R03_producer_budget_production3_overspent")
            S("producer","budget3", bud3, t3)
            def res(p):
                go(p, "Issue and return"); tab(p, "Currently out"); shot(p, "R04_resource_issue_return_currently_out")
            S("resource","resource", res, t1)
            br.close()
    finally:
        srv.terminate()
    print("SKIPPED:", SKIPPED)
main()
