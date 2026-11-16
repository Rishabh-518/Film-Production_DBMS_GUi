"""Permission tests (SRS section 9). Run: APP_DBNAME=film_test .venv/Scripts/python.exe tools/test_permissions.py

Destructive: it writes rows. It refuses to run against the real database.
"""
import os
import sys
import time
from datetime import date, datetime, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import accounts
import audit
import auth
import budget
import callsheets
import navigation
import records
import resources
import schedule
import team
from access import RuleError, PermissionDenied, can, visible_modules
from db import SETTINGS, transaction

ADMIN, PRODUCER, STAGE = {"Admin"}, {"Producer"}, {"Stage Management"}
DEPT, RESOURCE, FINANCE = {"Department Head"}, {"Resource Coordinator"}, {"Finance"}
CAST, VIEWER = {"Cast / Crew"}, {"Viewer"}

passed = failed = 0
# Each run books its own far-future day, so repeated runs on film_test do not clash.
RUN = int(time.time())
BASE = datetime(2100, 1, 1) + timedelta(days=RUN % 100000)


def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        print("FAIL:", name)


def allowed(name, fn, *args, **kwargs):
    try:
        result = fn(*args, **kwargs)
    except Exception as err:
        check(f"{name} (raised {err!r})", False)
        return None
    check(name, True)
    return result


def refused(name, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except RuleError:
        check(name, True)
        return
    except Exception as err:
        check(f"{name} (wrong error {err!r})", False)
        return
    check(f"{name} (was allowed)", False)


def one(sql, params=()):
    with transaction() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def pick_data():
    """A production with a Dept Head who has a department, plus another department and a cast member."""
    with transaction() as cur:
        cur.execute(
            """
            SELECT ra.production_id, ra.person_id AS dept_person, ra.department_id AS own_dept
            FROM RoleAssignment ra JOIN Production p ON p.production_id = ra.production_id
            WHERE ra.department_id IS NOT NULL AND p.status <> 'Archived'
              AND EXISTS (SELECT 1 FROM Department d WHERE d.production_id = ra.production_id
                          AND d.department_id <> ra.department_id)
              AND EXISTS (SELECT 1 FROM BudgetLine bl JOIN Budget b ON b.budget_id = bl.budget_id
                          WHERE b.production_id = ra.production_id)
            ORDER BY ra.production_id LIMIT 1
            """
        )
        row = cur.fetchone()
        cur.execute(
            "SELECT department_id FROM Department WHERE production_id = %s AND department_id <> %s LIMIT 1",
            (row["production_id"], row["own_dept"]),
        )
        row["other_dept"] = cur.fetchone()["department_id"]
        cur.execute(
            "SELECT person_id FROM RoleAssignment WHERE production_id = %s AND person_id <> %s LIMIT 1",
            (row["production_id"], row["dept_person"]),
        )
        row["cast_person"] = cur.fetchone()["person_id"]
        cur.execute(
            "SELECT person_id FROM Person WHERE person_id NOT IN "
            "(SELECT person_id FROM RoleAssignment WHERE production_id = %s) "
            "AND person_id NOT IN (SELECT person_id FROM auth.account WHERE person_id IS NOT NULL) LIMIT 1",
            (row["production_id"],),
        )
        row["outsider"] = cur.fetchone()["person_id"]
        cur.execute("SELECT venue_id FROM Venue LIMIT 1")
        row["venue"] = cur.fetchone()["venue_id"]
        return row


def test_matrix():
    check("accounts: admin only", can(ADMIN, "manage_accounts") and not any(
        can(c, "view_accounts") for c in (PRODUCER, STAGE, DEPT, RESOURCE, FINANCE, CAST, VIEWER)))
    check("records page: only classes that edit productions, venues or people", all(
        can(c, "view_records") for c in (ADMIN, PRODUCER, STAGE, RESOURCE)) and not any(
        can(c, "view_records") for c in (DEPT, FINANCE, CAST, VIEWER)))
    check("sidebar: producer and finance see no Admin group", not any(
        group == "Admin" for c in (PRODUCER, FINANCE) for group, _ in navigation.sections(c, True)))
    check("sidebar: admin sees the Admin group", any(group == "Admin" for group, _ in navigation.sections(ADMIN, True)))
    check("call sheets hidden from finance", not can(FINANCE, "view_call_sheets") and "Call sheets" not in visible_modules(FINANCE))
    check("viewer has no write action", not any(can(VIEWER, a) for a in (
        "manage_schedule", "propose_event", "manage_resources", "request_resource", "request_expense",
        "manage_budget", "manage_documents", "manage_assignments", "manage_people", "manage_venues",
        "acknowledge_call_sheet", "update_own_contact", "manage_call_sheets", "manage_accounts")))
    check("audit: finance and producer see it, stage does not", can(FINANCE, "view_audit") and can(PRODUCER, "view_audit") and not can(STAGE, "view_audit"))
    check("dept head cannot request expenses", not can(DEPT, "request_expense") and can(CAST, "request_expense"))


def test_accounts(data):
    email = "perm_test@film"
    refused("producer cannot create account", accounts.create_account, email, "secret1", data["outsider"], False, None, PRODUCER)
    refused("producer cannot reset password", accounts.reset_password, 1, "secret22", PRODUCER)
    refused("producer cannot list accounts", accounts.list_accounts, PRODUCER)
    check("list never has password_hash", all("password_hash" not in r for r in accounts.list_accounts(ADMIN)))
    refused("cast cannot list accounts", accounts.list_accounts, CAST)
    refused("account needs person or admin", accounts.create_account, email, "secret1", None, False, None, ADMIN)
    refused("short password", accounts.create_account, email, "123", data["outsider"], False, None, ADMIN)
    with transaction() as cur:
        cur.execute("DELETE FROM auth.account WHERE email = %s", (email,))
    account_id = allowed("admin creates account", accounts.create_account, email, "secret1", data["outsider"], False, "Viewer", ADMIN)
    check("new account can sign in", auth.authenticate(email, "secret1") is not None)
    refused("duplicate email", accounts.create_account, email, "secret1", data["cast_person"], False, None, ADMIN)
    allowed("admin disables", accounts.set_active, account_id, False, ADMIN, 0)
    check("disabled cannot sign in", auth.authenticate(email, "secret1") is None)
    allowed("admin enables", accounts.set_active, account_id, True, ADMIN, 0)
    allowed("admin resets password", accounts.reset_password, account_id, "newsecret", ADMIN)
    check("old password dead, new works", auth.authenticate(email, "secret1") is None and auth.authenticate(email, "newsecret") is not None)
    allowed("admin sets class", accounts.set_account_class, account_id, "Finance", ADMIN)
    refused("cannot disable yourself", accounts.set_active, account_id, False, ADMIN, account_id)
    with transaction() as cur:
        cur.execute("DELETE FROM auth.account WHERE email = %s", (email,))


def test_people_and_assignments(data):
    pid, dept, other = data["production_id"], data["dept_person"], data["other_dept"]
    today = date.today()
    refused("dept head cannot assign in another department", team.add_assignment, pid, data["cast_person"], "Assistant", other, today, today, DEPT, dept)
    refused("dept head cannot assign with no department", team.add_assignment, pid, data["cast_person"], "Assistant", None, today, today, DEPT, dept)
    allowed("dept head assigns in own department", team.add_assignment, pid, data["cast_person"], "Assistant", data["own_dept"], today, today, DEPT, dept)
    refused("stage cannot manage departments", team.add_department, pid, "Nope", STAGE)
    refused("cast cannot assign", team.add_assignment, pid, data["cast_person"], "X", data["own_dept"], today, today, CAST, data["cast_person"])
    refused("viewer cannot add task", team.add_task, pid, "T", data["own_dept"], None, today, "Low", VIEWER)
    refused("dept head task in other department", team.add_task, pid, "T", other, None, today, "Low", DEPT, dept)
    allowed("dept head task in own department", team.add_task, pid, "Perm test task", data["own_dept"], None, today, "Low", DEPT, dept)
    task = one("SELECT task_id FROM Task WHERE title = 'Perm test task' ORDER BY task_id DESC LIMIT 1")
    allowed("producer assigns any task", team.assign_task, pid, task["task_id"], data["cast_person"], PRODUCER, 0)
    with transaction() as cur:
        cur.execute("UPDATE Task SET department_id = %s WHERE task_id = %s", (other, task["task_id"]))
    refused("dept head cannot assign other department's task", team.assign_task, pid, task["task_id"], dept, DEPT, dept)
    refused("viewer cannot add document", team.add_document, pid, "D", "Script", "x", VIEWER)
    allowed("dept head adds document", team.add_document, pid, "Perm doc", "Script", "x", DEPT)
    refused("cast cannot add document", team.add_document, pid, "D", "Script", "x", CAST)
    # self-service
    me = data["cast_person"]
    allowed("cast edits own contact", records.update_own_contact, me, f"perm_cast{RUN}@film.test", "555", CAST, me)
    refused("cast cannot edit someone else", records.update_own_contact, data["outsider"], "a@b.c", "1", CAST, me)
    refused("cast cannot edit person record", records.update_person, me, "Renamed", "a@b.c", "1", CAST)
    refused("viewer cannot add person", records.add_person, "Z", "z@z.z", "1", VIEWER)
    allowed("stage adds person", records.add_person, "Perm Person", f"perm_person{RUN}@film.test", "1", STAGE)
    refused("viewer cannot add venue", records.add_venue, "V", "a", "c", 10, VIEWER)
    allowed("resource coordinator adds venue", records.add_venue, "Perm Venue", "a", "c", 10, RESOURCE)


def test_schedule(data):
    pid = data["production_id"]
    start = BASE.replace(hour=9)
    end = start + timedelta(hours=2)
    refused("viewer cannot create event", schedule.create_event, pid, data["venue"], "Rehearsal", start, end, classes=VIEWER)
    refused("cast cannot create event", schedule.create_event, pid, data["venue"], "Rehearsal", start, end, classes=CAST)
    event_id = allowed("dept head proposes event", schedule.create_event, pid, data["venue"], "Rehearsal", start, end, "Confirmed", classes=DEPT)
    check("dept head event is saved as Proposed", schedule.get_event(event_id)["status"] == "Proposed")
    refused("dept head cannot reschedule", schedule.reschedule_event, event_id, start, end, data["venue"], classes=DEPT)
    refused("dept head cannot approve", schedule.propose_decision, event_id, True, DEPT)
    refused("cast cannot approve", schedule.propose_decision, event_id, True, CAST)
    allowed("stage approves proposal", schedule.propose_decision, event_id, True, STAGE)
    check("approved becomes Scheduled", schedule.get_event(event_id)["status"] == "Scheduled")
    refused("cannot approve a non-proposed event", schedule.propose_decision, event_id, True, PRODUCER)
    other = allowed("producer creates event directly", schedule.create_event, pid, data["venue"], "Rehearsal", start + timedelta(days=1), end + timedelta(days=1), "Scheduled", classes=PRODUCER)
    check("producer event keeps status", schedule.get_event(other)["status"] == "Scheduled")
    allowed("producer adds participant", schedule.add_participant, event_id, data["cast_person"], "Assigned", False, classes=PRODUCER)
    refused("viewer cannot add participant", schedule.add_participant, event_id, data["outsider"], classes=VIEWER)
    own = schedule.list_events(pid, "All", data["cast_person"])
    with transaction() as cur:
        cur.execute("SELECT event_id FROM EventParticipation WHERE person_id = %s", (data["cast_person"],))
        theirs = {r["event_id"] for r in cur.fetchall()}
    check("cast sees only their events", {e["event_id"] for e in own} <= theirs and event_id in theirs)
    check("others see more events", len(schedule.list_events(pid)) > len(own))
    refused("viewer cannot cancel event", schedule.set_event_status, event_id, "Cancelled", classes=VIEWER)
    refused("cannot make an event Proposed by hand", schedule.set_event_status, event_id, "Proposed", classes=PRODUCER)
    return event_id


def test_call_sheets(data, event_id):
    check("finance cannot see call sheets", not can(FINANCE, "view_call_sheets"))
    refused("cast cannot generate", callsheets.generate_call_sheet, event_id, CAST)
    sheet = allowed("stage generates", callsheets.generate_call_sheet, event_id, STAGE)
    refused("viewer cannot issue", callsheets.issue_call_sheet, sheet, VIEWER)
    allowed("producer issues", callsheets.issue_call_sheet, sheet, PRODUCER)
    refused("viewer cannot acknowledge", callsheets.acknowledge, sheet, data["cast_person"], VIEWER)
    allowed("cast acknowledges", callsheets.acknowledge, sheet, data["cast_person"], CAST)
    proposed = schedule.create_event(data["production_id"], data["venue"], "Rehearsal", BASE.replace(hour=14), BASE.replace(hour=16), classes=DEPT)
    refused("no call sheet for a proposal", callsheets.generate_call_sheet, proposed, STAGE)


def test_resource_requests(data, event_id):
    item = one("SELECT resource_id FROM Resource WHERE status = 'Available' AND resource_condition IN ('Good','Fair') AND resource_id NOT IN (SELECT resource_id FROM EventResourceReservation) LIMIT 1")["resource_id"]
    bad = one("SELECT resource_id FROM Resource WHERE status IN ('Damaged','Under Repair') AND resource_id NOT IN (SELECT resource_id FROM EventResourceReservation) LIMIT 1")
    refused("stage cannot request (not a requester)", schedule.request_resource, event_id, item, STAGE, data["cast_person"])
    refused("viewer cannot request", schedule.request_resource, event_id, item, VIEWER, data["cast_person"])
    refused("outsider cannot request", schedule.request_resource, event_id, item, CAST, data["outsider"])
    allowed("cast requests", schedule.request_resource, event_id, item, CAST, data["cast_person"])
    status = one("SELECT reservation_status s FROM EventResourceReservation WHERE event_id = %s AND resource_id = %s", (event_id, item))["s"]
    check("request stored as Requested", status == "Requested")
    refused("duplicate request", schedule.request_resource, event_id, item, DEPT, data["dept_person"])
    check("request is in the queue", any(r["resource_id"] == item for r in schedule.list_requests(data["production_id"])))
    refused("dept head cannot confirm", schedule.decide_request, event_id, item, True, DEPT)
    refused("producer cannot confirm", schedule.decide_request, event_id, item, True, PRODUCER)
    allowed("resource coordinator confirms", schedule.decide_request, event_id, item, True, RESOURCE)
    check("request is Confirmed", one("SELECT reservation_status s FROM EventResourceReservation WHERE event_id = %s AND resource_id = %s", (event_id, item))["s"] == "Confirmed")
    refused("cannot decide twice", schedule.decide_request, event_id, item, False, RESOURCE)
    if bad:
        allowed("dept head requests a damaged item", schedule.request_resource, event_id, bad["resource_id"], DEPT, data["dept_person"])
        refused("damaged item cannot be confirmed", schedule.decide_request, event_id, bad["resource_id"], True, ADMIN)
        allowed("coordinator rejects it", schedule.decide_request, event_id, bad["resource_id"], False, RESOURCE)
    # a second event at the same time clashes on the confirmed item
    clash_event = schedule.create_event(data["production_id"], None, "Rehearsal", BASE.replace(hour=9), BASE.replace(hour=11), classes=DEPT)
    schedule.request_resource(clash_event, item, CAST, data["cast_person"])
    try:
        schedule.decide_request(clash_event, item, True, RESOURCE)
        check("clash blocks confirm", False)
    except RuleError:
        check("clash blocks confirm", True)
    allowed("clash can be confirmed on purpose", schedule.decide_request, clash_event, item, True, RESOURCE, True)
    refused("cast cannot add resource", resources.add_resource, "X", "Y", "Good", "Available", CAST)
    refused("dept head cannot delete resource", resources.delete_resource, item, DEPT)
    allowed("coordinator adds resource", resources.add_resource, "Perm light", "Light", "Good", "Available", RESOURCE)
    refused("viewer cannot reserve", schedule.reserve_resource, event_id, item, "Tentative", classes=VIEWER)


def test_budget(data):
    pid = data["production_id"]
    lines_by_dept = {}
    draft = one("SELECT b.budget_id FROM Budget b JOIN BudgetLine bl ON bl.budget_id = b.budget_id WHERE b.production_id = %s LIMIT 1", (pid,))["budget_id"]
    every = budget.list_lines(draft)
    own = budget.list_lines(draft, budget.department_filter(pid, DEPT, data["dept_person"]))
    check("dept head sees own lines only", all(l["department_id"] == data["own_dept"] for l in own) and len(own) <= len(every))
    check("producer sees every line", budget.department_filter(pid, PRODUCER, 0) is None)
    line = every[0]["line_id"]
    refused("dept head cannot submit expense", budget.add_expense, line, "V", date.today(), 5, "x", DEPT, data["dept_person"])
    refused("viewer cannot submit expense", budget.add_expense, line, "V", date.today(), 5, "x", VIEWER, 1)
    refused("unassigned cast cannot submit", budget.add_expense, line, "V", date.today(), 5, "x", CAST, data["outsider"])
    result = allowed("assigned cast submits", budget.add_expense, line, "Perm vendor", date.today(), 5, "x", CAST, data["cast_person"])
    check("cast expense is Pending", one("SELECT approval_status s FROM Expense WHERE expense_id = %s", (result[0],))["s"] == "Pending")
    allowed("resource coordinator submits", budget.add_expense, line, "Perm vendor 2", date.today(), 5, "x", RESOURCE, data["outsider"])
    refused("cast cannot approve", budget.decide_expense, result[0], "Approved", CAST)
    allowed("finance approves", budget.decide_expense, result[0], "Approved", FINANCE)
    refused("cast cannot add line", budget.add_line, draft, data["own_dept"], "X", 1, 1, CAST)
    refused("dept head cannot edit line", budget.update_line, line, 1, 1, DEPT)
    refused("viewer cannot create version", budget.create_budget_version, pid, VIEWER)
    check("only finance and producer have expense approval", can(FINANCE, "approve_expense") and not can(DEPT, "approve_expense"))


def test_audit(data):
    pid = data["production_id"]
    check("admin sees all productions", len(audit.audit_sections(None, ADMIN)) == 3)
    refused("admin-only all-production view", audit.audit_sections, None, PRODUCER, 1)
    refused("stage has no audit", audit.audit_sections, pid, STAGE, 1)
    refused("cast has no audit", audit.audit_sections, pid, CAST, data["cast_person"])
    refused("producer outside the production", audit.audit_sections, pid, PRODUCER, data["outsider"])
    producer = one("SELECT person_id FROM RoleAssignment WHERE production_id = %s LIMIT 1", (pid,))["person_id"]
    check("producer sees own production", len(audit.audit_sections(pid, PRODUCER, producer)) == 3)
    sections = audit.audit_sections(pid, FINANCE, 1)
    check("finance sees expenses only", [t for t, _ in sections] == ["Expense approvals"])


def main():
    if SETTINGS["dbname"] == "Film production project":
        sys.exit("Refusing to run against the real database.")
    print("Database:", SETTINGS["dbname"])
    data = pick_data()
    test_matrix()
    test_accounts(data)
    test_people_and_assignments(data)
    event_id = test_schedule(data)
    test_call_sheets(data, event_id)
    test_resource_requests(data, event_id)
    test_budget(data)
    test_audit(data)
    print(f"{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
