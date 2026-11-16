"""Final screenshots: numbered 01 to 05, the account and archive shots, and retakes of R01, R02, R03 and R05.
Run from production_app on film_demo:  .venv/Scripts/python.exe tools/shots_final.py
"""
import subprocess
import sys
import time
import urllib.request

import take_screenshots as t
from playwright.sync_api import sync_playwright

t.PORT = 8621
t.URL = f"http://localhost:{t.PORT}"
OUT = t.OUT_DIR
ONLY = sys.argv[1:]
TEMP_LOGIN = "temp.user@silverreelstudios.com"


def save(page, name):
    OUT.mkdir(parents=True, exist_ok=True)
    t.settle(page, 800)
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
    print("saved", name)


def pick_by_keyboard(page, label, text):
    t.visible(page, label).click()
    page.keyboard.type(text)
    t.settle(page, 800)
    page.keyboard.press("Enter")
    t.settle(page, 1000)


def open_production(page, title, show_all=False):
    """Like take_screenshots.open_production, but waits longer for the grid and clicks the row again if needed."""
    t.leave_production(page)
    page.get_by_role("tab", name="Productions", exact=True).click()
    t.settle(page, 1500)
    if show_all:
        page.get_by_text("Show all (include completed and archived)").click()
        t.settle(page, 1500)
    page.get_by_label("Search by title", exact=True).fill(title)
    page.keyboard.press("Enter")
    t.settle(page, 2500)
    grid = page.get_by_test_id("stDataFrame").locator("visible=true").first.bounding_box()
    for _ in range(3):
        page.mouse.click(grid["x"] + 70, grid["y"] + 52)
        t.settle(page, 2500)
        if page.get_by_role("button", name="Switch production").count():
            return
    raise RuntimeError("could not open " + title)


def run(name, who, steps, production=None, show_all=False):
    if ONLY and name not in ONLY:
        return
    page = None
    try:
        page = t.Browser.login(browser, who)
        if production:
            open_production(page, production, show_all)
        steps(page)
    except Exception as err:  # noqa: BLE001
        print("SKIPPED", name, str(err).splitlines()[0][:150])
    finally:
        if page:
            page.context.close()


def login_page(page):
    page.goto(t.URL)
    login, password = t.credentials("admin")
    page.get_by_label("Email", exact=True).fill(login)
    page.get_by_label("Password", exact=True).fill(password)
    t.settle(page, 500)
    save(page, "01_login_password_hidden")


def accounts_flow(page):
    t.go(page, "Accounts")
    t.tab(page, "Change an account")
    pick_by_keyboard(page, "Account", "temp.user")
    t.press(page, "Disable this account")
    save(page, "36_accounts_disable")


def reset_flow(page):
    t.go(page, "Accounts")
    t.tab(page, "Change an account")
    pick_by_keyboard(page, "Account", "temp.user")
    t.fill(page, "New password", "newpass99")
    t.press(page, "Reset password")
    save(page, "37_accounts_password_reset")


def archived_flow(page):
    t.go(page, "Schedule")
    t.tab(page, "New event")
    t.press(page, "Create event")
    save(page, "38_archived_production_read_only_refusal")


def budget3(page):
    t.go(page, "Budget and expenses")
    page.get_by_label("Budget version", exact=True).click()
    t.settle(page, 600)
    page.get_by_role("option").filter(has_text="Approved").first.click()
    t.settle(page, 1500)
    save(page, "R03_producer_budget_production3_overspent")


def audit_all(page):
    t.go(page, "Audit history")
    save(page, "R05_admin_audit_history")


def picker_shots(page):
    page.get_by_role("tab", name="Productions", exact=True).click()
    t.settle(page, 1500)
    save(page, "04_picker_active_first")
    page.get_by_text("Show all (include completed and archived)").click()
    t.settle(page, 1500)
    save(page, "05_picker_show_all")


def make_temp_account():
    """A spare account for the disable and reset shots, so no demo login is changed."""
    import accounts
    if not t.query("SELECT 1 FROM auth.account WHERE email = %s", (TEMP_LOGIN,)):
        accounts.create_account(TEMP_LOGIN, "Temp@Silver2026", None, True, None, {"Admin"})


def main():
    global browser
    server = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", str(t.PORT),
         "--server.headless", "true", "--browser.gatherUsageStats", "false"],
        cwd=t.APP_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    try:
        for _ in range(60):
            try:
                if urllib.request.urlopen(f"{t.URL}/_stcore/health").read() == b"ok":
                    break
            except OSError:
                time.sleep(1)
        make_temp_account()
        archived = t.query("SELECT title FROM Production WHERE status = 'Archived' ORDER BY production_id LIMIT 1")[0]["title"]
        with sync_playwright() as pw:
            browser = t.Browser(pw)
            if not ONLY:
                page = browser.browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
                login_page(page)
                page.context.close()
            run("02", "admin", lambda p: save(p, "02_home_admin"))
            run("03", "producer", lambda p: save(p, "03_home_producer"))
            run("04", "admin", picker_shots)
            run("36", "admin", accounts_flow)
            run("37", "admin", reset_flow)
            run("38", "admin", archived_flow, archived, True)
            run("R01", "actor", lambda p: save(p, "R01_home_needs_attention_actor"))
            run("R02", "actor", lambda p: save(p, "R02_sidebar_production1_actor"), t.title_of(1))
            run("R03", "producer", budget3, t.title_of(3))
            run("R05", "admin", audit_all)
    finally:
        server.terminate()


if __name__ == "__main__":
    main()
