"""Start the app on the film_demo database and save numbered screenshots for the report.

Before running, rebuild the demo data:  APP_DBNAME=film_demo .venv/Scripts/python.exe tools/seed_demo.py
Run from production_app:  .venv/Scripts/python.exe tools/take_screenshots.py
Optional arguments run only some functions, for example:  take_screenshots.py shots_finance
Several shots write to film_demo (issue, approve, create), so run seed_demo.py again afterwards.
"""
import itertools
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

os.environ["APP_DBNAME"] = "film_demo"
APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from playwright.sync_api import sync_playwright  # noqa: E402

from db import transaction  # noqa: E402
from setup_auth import demo_logins  # noqa: E402

OUT_DIR = APP_DIR.parent / "Final_Improved" / "Final_Report" / "screenshots"
PORT = 8599
URL = f"http://localhost:{PORT}"
SKIPPED = []
COUNTER = itertools.count(int(os.environ.get("FIRST_SHOT", "6")))  # 01 to 05 and the R-prefixed shots belong to the read-only script
# Short names for the demo accounts, in the order setup_auth.py creates them.
LOGINS = ["admin", "producer", "director", "stage", "dept", "finance", "actor", "resource", "viewer"]


def credentials(who):
    """(login, password) of a demo account, for example credentials("producer")."""
    return dict(zip(LOGINS, demo_logins()))[who]


def query(sql, params=()):
    with transaction() as cur:
        cur.execute(sql, params)
        return cur.fetchall() if cur.description else []


def title_of(production_id):
    return query("SELECT title FROM Production WHERE production_id = %s", (production_id,))[0]["title"]


class Browser:
    def __init__(self, playwright):
        self.browser = playwright.chromium.launch()

    def login(self, email):
        context = self.browser.new_context(viewport={"width": 1400, "height": 2400})
        page = context.new_page()
        self.last_page = page
        page.goto(URL)
        login, password = credentials(email)
        page.get_by_label("Email", exact=True).fill(login)
        page.get_by_label("Password", exact=True).fill(password)
        page.get_by_role("button", name="Log in").click()
        page.get_by_role("heading", name="Home", exact=True).wait_for(timeout=20000)
        settle(page, 1500)
        return page


def settle(page, ms=1000):
    page.wait_for_timeout(ms)


def shot(page, name):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    settle(page, 800)
    file_name = f"{next(COUNTER):02d}_{name}"
    page.screenshot(path=str(OUT_DIR / f"{file_name}.png"), full_page=True)
    print("saved", file_name)


def leave_production(page):
    if page.get_by_role("button", name="Switch production").count():
        page.get_by_role("button", name="Switch production").click()
        settle(page, 1500)


def open_production(page, title, show_all=False):
    leave_production(page)
    page.get_by_role("tab", name="Productions", exact=True).click()
    settle(page)
    if show_all:
        page.get_by_text("Show all (include completed and archived)").click()
        settle(page)
    page.get_by_label("Search by title", exact=True).fill(title)
    page.keyboard.press("Enter")
    settle(page, 1500)
    grid = page.get_by_test_id("stDataFrame").locator("visible=true").first.bounding_box()
    page.mouse.click(grid["x"] + 70, grid["y"] + 35 + 17)
    page.get_by_role("button", name="Switch production").wait_for(timeout=15000)
    settle(page)


def go(page, name):
    page.locator("[data-testid=stSidebar]").get_by_role("button", name=name, exact=True).click()
    settle(page, 1500)


def tab(page, name):
    page.get_by_role("tab", name=name, exact=True).click()
    settle(page, 800)


def visible(page, label):
    return page.get_by_label(label, exact=True).locator("visible=true").first


def choose(page, label, text):
    box = visible(page, label)
    box.click()
    page.keyboard.type(text)
    settle(page, 700)
    page.get_by_role("option").filter(has_text=text).first.click()
    settle(page, 800)


def fill(page, label, value):
    visible(page, label).fill(value)
    page.keyboard.press("Tab")
    settle(page, 400)


def press(page, name):
    page.get_by_role("button", name=name).locator("visible=true").first.click()
    settle(page, 1500)


def attempt_shot(name, how, func):
    """Run one step. A failure goes to the manual checklist."""
    try:
        func()
    except Exception as err:  # noqa: BLE001
        SKIPPED.append((name, how, str(err).splitlines()[0][:120]))
        print("SKIPPED", name, "-", str(err).splitlines()[0][:120])


def shots_documents(browser):
    page = browser.login("producer")
    open_production(page, title_of(1))
    go(page, "Documents")
    press(page, "Approve")
    shot(page, "document_approved")
    page.context.close()


def shots_contact(browser):
    page = browser.login("actor")
    tab(page, "My details")
    fill(page, "Phone", "9876500006")
    press(page, "Save my details")
    shot(page, "cast_own_contact_saved")
    page.context.close()


def admin_step(browser, name, how, steps):
    """Each admin shot gets a fresh login, so one failure cannot leave the next one stuck."""
    page = browser.login("admin")
    attempt_shot(name, how, lambda: steps(page))
    page.context.close()


def open_event(page, event_id):
    production_id = query("SELECT production_id FROM ProductionEvent WHERE event_id = %s", (event_id,))[0]["production_id"]
    open_production(page, title_of(production_id))
    go(page, "Schedule")
    tab(page, "Change an event")
    choose(page, "Event", f"#{event_id} ")


def shots_admin(browser):
    def create(page):
        go(page, "Accounts")
        tab(page, "Create account")
        fill(page, "Email", "new.user@silverreelstudios.com")
        fill(page, "Password", "demo1234")
        press(page, "Create account")
        shot(page, "accounts_created")

    def disable(page):
        go(page, "Accounts")
        tab(page, "Change an account")
        choose(page, "Account", "new.user@silverreelstudios.com")
        press(page, "Disable this account")
        shot(page, "accounts_disabled")

    def reset(page):
        go(page, "Accounts")
        tab(page, "Change an account")
        choose(page, "Account", "new.user@silverreelstudios.com")
        fill(page, "New password", "newpass99")
        press(page, "Reset password")
        shot(page, "accounts_password_reset")

    def person_clash(page):
        open_event(page, 41)
        choose(page, "Person", "Yash Trivedi")
        press(page, "Add or update")
        shot(page, "clash_person_warning")

    def venue_clash(page):
        open_event(page, 40)
        press(page, "Save new time")
        shot(page, "clash_venue_warning")

    def resource_clash(page):
        open_event(page, 48)
        tool = query("SELECT resource_name, status FROM Resource WHERE resource_id = 99")[0]
        choose(page, "Resource", f"{tool['resource_name']} ({tool['status']})")
        press(page, "Reserve or update")
        shot(page, "clash_resource_warning")

    def archived(page):
        old = query("SELECT title FROM Production WHERE status = 'Archived' ORDER BY production_id LIMIT 1")[0]["title"]
        open_production(page, old, show_all=True)
        go(page, "Schedule")
        tab(page, "New event")
        press(page, "Create event")
        shot(page, "archived_production_write_refused")

    for name, how, steps in (
        ("accounts_created", "Admin, Accounts, Create account", create),
        ("accounts_disabled", "Admin, Accounts, Change an account, Disable", disable),
        ("accounts_password_reset", "Admin, Accounts, Change an account, Reset password", reset),
        ("clash_person_warning", "Admin, Schedule, Change an event 41, add Yash Trivedi", person_clash),
        ("clash_venue_warning", "Admin, Schedule, Change an event 40, Save new time", venue_clash),
        ("clash_resource_warning", "Admin, Schedule, Change an event 48, reserve Tool Box", resource_clash),
        ("archived_production_write_refused", "Admin, open an Archived production, Schedule, New event, Create event", archived),
    ):
        admin_step(browser, name, how, steps)


def shots_resource(browser):
    page = browser.login("resource")
    open_production(page, title_of(1))
    go(page, "Catalogue")
    shot(page, "module_catalogue_resource")

    def confirm_request():
        shot(page, "resource_requests_before_confirm")
        press(page, "Confirm request")
        shot(page, "resource_request_confirmed")

    attempt_shot("resource_request_confirmed", "Resource Coordinator, Catalogue, Open request, Confirm request", confirm_request)
    go(page, "Issue and return")

    def blocked_issue():
        bad = query("SELECT resource_name, status FROM Resource WHERE resource_id = 81")[0]
        choose(page, "Resource", f"{bad['resource_name']} ({bad['status']})")
        press(page, "Issue")
        shot(page, "issue_blocked_damaged_item")

    attempt_shot("issue_blocked_damaged_item", "Resource Coordinator, Issue and return, pick a Damaged item, Issue", blocked_issue)

    def issue_ok():
        go(page, "Issue and return")
        free = query("SELECT resource_name, status FROM Resource WHERE status = 'Available' "
                     "AND resource_condition = 'Good' ORDER BY resource_id LIMIT 1")[0]
        choose(page, "Resource", f"{free['resource_name']} ({free['status']})")
        press(page, "Issue")
        shot(page, "issue_success")

    attempt_shot("issue_success", "Resource Coordinator, Issue and return, pick an Available item, Issue", issue_ok)

    def return_ok():
        tab(page, "Return")
        press(page, "Record return")
        shot(page, "return_recorded")

    attempt_shot("return_recorded", "Resource Coordinator, Issue and return, Return tab, Record return", return_ok)
    tab(page, "Overdue returns")
    shot(page, "overdue_returns")
    tab(page, "Currently out")
    shot(page, "items_currently_out")
    page.context.close()


def shots_stage(browser):
    page = browser.login("stage")
    open_production(page, title_of(1))
    go(page, "Call sheets")
    actor_event = query(
        "SELECT e.event_id FROM ProductionEvent e JOIN EventParticipation ep ON ep.event_id = e.event_id "
        "WHERE e.production_id = 1 AND ep.person_id = 6 AND e.status NOT IN ('Cancelled', 'Proposed') "
        "AND e.start_datetime > now() ORDER BY e.start_datetime LIMIT 1")[0]["event_id"]

    def generate():
        tab(page, "Generate from an event")
        choose(page, "Event", f"#{actor_event} ")
        press(page, "Generate new revision")
        shot(page, "call_sheet_generated_draft")
        tab(page, "Issue a draft")
        press(page, "Issue this revision")
        shot(page, "call_sheet_issued")

    attempt_shot("call_sheet_generated_draft", "Stage Manager, Call sheets, Generate from an event, then Issue a draft", generate)

    def approve_proposal():
        go(page, "Schedule")
        tab(page, "Proposals")
        shot(page, "proposals_waiting_for_stage")
        press(page, "Approve (becomes Scheduled)")
        shot(page, "proposal_approved_by_stage")

    attempt_shot("proposal_approved_by_stage", "Stage Manager, Schedule, Proposals, Approve", approve_proposal)
    page.context.close()


def shots_dept(browser):
    page = browser.login("dept")
    open_production(page, title_of(1))
    go(page, "Schedule")
    shot(page, "dept_head_schedule_proposal_form")

    def propose():
        press(page, "Create event")
        shot(page, "dept_head_proposal_created")

    attempt_shot("dept_head_proposal_created", "Department Head, Schedule, Create event (saved as Proposed)", propose)

    def denied():
        go(page, "People and tasks")
        tab(page, "Tasks")
        other = query(
            "SELECT t.task_id FROM Task t WHERE t.production_id = 1 AND t.department_id IS NOT NULL "
            "AND t.department_id NOT IN (SELECT department_id FROM RoleAssignment "
            "WHERE production_id = 1 AND person_id = 4 AND department_id IS NOT NULL) ORDER BY t.task_id LIMIT 1")[0]["task_id"]
        choose(page, "Task", f"#{other} ")
        press(page, "Change status")
        shot(page, "permission_denied_other_department")

    attempt_shot("permission_denied_other_department", "Department Head, People and tasks, Tasks, change status of another department's task", denied)
    page.context.close()


def shots_actor(browser):
    page = browser.login("actor")
    open_production(page, title_of(1))

    def acknowledge():
        go(page, "Call sheets")
        shot(page, "cast_call_sheets_waiting")
        press(page, "Acknowledge call sheet")
        shot(page, "call_sheet_acknowledged")

    attempt_shot("call_sheet_acknowledged", "Actor, Call sheets, Acknowledge call sheet", acknowledge)

    def request():
        go(page, "Catalogue")
        item = query("SELECT resource_name, status FROM Resource WHERE status = 'Available' "
                     "ORDER BY resource_id DESC LIMIT 1")[0]
        choose(page, "Resource to request", f"{item['resource_name']} ({item['status']})")
        press(page, "Send request")
        shot(page, "cast_resource_request_sent")

    attempt_shot("cast_resource_request_sent", "Actor, Catalogue, pick event and resource, Send request", request)
    page.context.close()


def shots_finance(browser):
    page = browser.login("finance")
    open_production(page, title_of(1))
    go(page, "Budget and expenses")
    shot(page, "budget_production_1_near_limit")

    def pending_approval():
        tab(page, "Expenses")
        shot(page, "expenses_pending")
        press(page, "Approve")
        shot(page, "expense_approved_by_finance")

    attempt_shot("expense_approved_by_finance", "Finance, Budget and expenses, Expenses, Approve", pending_approval)

    def overspent():
        open_production(page, title_of(3))
        go(page, "Budget and expenses")
        shot(page, "budget_production_3_overspent")

    attempt_shot("budget_production_3_overspent", "Finance, open production 3, Budget and expenses", overspent)
    page.context.close()


def wait_for_app():
    for _ in range(60):
        try:
            if urllib.request.urlopen(f"{URL}/_stcore/health").read() == b"ok":
                return
        except OSError:
            time.sleep(1)
    raise RuntimeError("The app did not start.")


def main():
    server = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", str(PORT),
         "--server.headless", "true", "--browser.gatherUsageStats", "false"],
        cwd=APP_DIR, stdout=open(os.environ.get("SERVER_LOG", os.devnull), "w"), stderr=subprocess.STDOUT,
    )
    try:
        wait_for_app()
        with sync_playwright() as playwright:
            # Order matters: the Department Head's proposal and the actor's resource request
            # are approved later by the Stage Manager and the Resource Coordinator.
            for run in (shots_admin, shots_dept, shots_actor, shots_stage, shots_resource,
                        shots_finance, shots_documents, shots_contact):
                if len(sys.argv) > 1 and run.__name__ not in sys.argv[1:]:
                    continue
                browser = Browser(playwright)
                try:
                    run(browser)
                except Exception as err:  # noqa: BLE001
                    SKIPPED.append((run.__name__, "see the function in tools/take_screenshots.py",
                                    str(err).splitlines()[0][:120]))
                    print("FAILED", run.__name__, str(err).splitlines()[0][:200])
                    debug = os.environ.get("DEBUG_DIR")
                    if debug and getattr(browser, "last_page", None):
                        browser.last_page.screenshot(path=f"{debug}/{run.__name__}.png")
                finally:
                    browser.browser.close()
    finally:
        server.terminate()
    lines = ["# Screenshots to take by hand", "",
             "Log in with password 1234 on film_demo (run_demo.ps1). Save into Final_Report/screenshots.", ""]
    for name, how, why in SKIPPED:
        lines.append(f"- {name}: {how}. (script stopped: {why})")
    if not SKIPPED:
        lines.append("Nothing left: every planned shot was taken by tools/take_screenshots.py.")
    (APP_DIR / "SCREENSHOT_CHECKLIST.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
