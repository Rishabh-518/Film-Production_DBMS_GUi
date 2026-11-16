"""Calls the module functions directly against the film_test copy.

Run from production_app:  .venv/Scripts/python.exe tools/smoke_test.py
"""
import logging
import random
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

os.environ["APP_DBNAME"] = "film_test"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from access import ClashError, PermissionDenied, RuleError  # noqa: E402,F401
from db import transaction  # noqa: E402

logging.disable(logging.WARNING)
results = []
NOW = datetime.now().replace(microsecond=0)
RUN_DAY = datetime(2040, 1, 1) + timedelta(days=random.randint(0, 3000))
ADMIN, RES, FIN = {"Admin"}, {"Resource Coordinator"}, {"Finance"}


def check(name, condition, detail=""):
    results.append((name, bool(condition)))
    note = f"  [{detail}]" if detail and not condition else ""
    print(("PASS " if condition else "FAIL ") + name + note)


def raises(name, error, func, *args, **kwargs):
    try:
        func(*args, **kwargs)
    except error as err:
        check(name, True)
        return err
    except Exception as err:  # noqa: BLE001
        check(name, False, f"wrong error {type(err).__name__}: {err}")
        return None
    check(name, False, "no error raised")
    return None


def scalar(sql, params=()):
    with transaction() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return next(iter(row.values())) if row else None


def run(sql, params=()):
    with transaction() as cur:
        cur.execute(sql, params)


def test_resources():
    import movements
    import resources

    check("resource: add", resources.add_resource("ZZ Test Lamp", "Light", "Good", "Available", RES) == 1)
    rid = scalar("SELECT resource_id FROM Resource WHERE resource_name = 'ZZ Test Lamp'")
    found = resources.list_resources("zz test", "Light", "Available", "Good")
    check("resource: search and filters", len(found) == 1)
    check("resource: edit", resources.update_resource(rid, "ZZ Test Lamp 2", "Light", "Fair", "Available", RES) == 1)
    check("resource: edit stored",
          scalar("SELECT resource_condition FROM Resource WHERE resource_id = %s", (rid,)) == "Fair")
    err = raises("resource: delete with history blocked", RuleError, resources.delete_resource,
                 scalar("SELECT resource_id FROM ResourceMovement LIMIT 1"), RES)
    check("resource: friendly delete message", err is not None and "can't be deleted" in str(err))
    person = scalar("SELECT person_id FROM Person ORDER BY person_id LIMIT 1")

    raises("issue: expected return before issue", RuleError, movements.issue_resource,
           rid, person, NOW - timedelta(days=1), classes=RES)
    mid = movements.issue_resource(rid, person, NOW + timedelta(days=1), classes=RES)
    check("issue: status is Issued",
          scalar("SELECT status FROM Resource WHERE resource_id = %s", (rid,)) == "Issued")
    raises("issue: already issued blocked", RuleError, movements.issue_resource,
           rid, person, NOW + timedelta(days=1), classes=RES)
    for status in ("Damaged", "Under Repair", "Reserved"):
        run("UPDATE Resource SET status = %s WHERE resource_id = %s", (status, rid))
        raises(f"issue: {status} blocked", RuleError, movements.issue_resource,
               rid, person, NOW + timedelta(days=1), classes=RES)
    run("UPDATE Resource SET status = 'Available' WHERE resource_id = %s", (rid,))
    before = scalar("SELECT COUNT(*) FROM ResourceMovement")
    try:
        movements.issue_resource(rid, 999999, NOW + timedelta(days=1), classes=RES)
    except Exception:  # noqa: BLE001
        pass
    check("issue: rollback keeps status",
          scalar("SELECT status FROM Resource WHERE resource_id = %s", (rid,)) == "Available")
    check("issue: rollback keeps movements", scalar("SELECT COUNT(*) FROM ResourceMovement") == before)
    check("issue: overdue list works", isinstance(movements.overdue_returns(), list))
    run("UPDATE Resource SET status = 'Issued' WHERE resource_id = %s", (rid,))
    check("return: damaged sets Damaged", movements.record_return(mid, "Damaged", classes=RES) == "Damaged")
    check("return: return time set",
          scalar("SELECT actual_return FROM ResourceMovement WHERE movement_id = %s", (mid,)) is not None)
    raises("return: twice blocked", RuleError, movements.record_return, mid, "Good", classes=RES)


PRODUCER_CLASSES = {"Producer"}
STATE = {}
CAST = {"Cast / Crew"}


def fixtures():
    import records

    with transaction() as cur:
        cur.execute("SELECT person_id FROM Person ORDER BY person_id LIMIT 4")
        people = [r["person_id"] for r in cur.fetchall()]
    records.add_venue("ZZ Test Hall", "1 Test Road", "none", 50, ADMIN)
    venue = scalar("SELECT venue_id FROM Venue WHERE venue_name = 'ZZ Test Hall'")
    records.add_venue("ZZ Other Hall", "2 Test Road", "none", 80, ADMIN)
    other_venue = scalar("SELECT venue_id FROM Venue WHERE venue_name = 'ZZ Other Hall'")
    prod = records.create_production("ZZ Test Production", "Play", datetime(2031, 1, 1).date(),
                                     datetime(2031, 12, 31).date(), "Planning", PRODUCER_CLASSES,
                                     producer_person_id=people[0])
    STATE.update(people=people, venue=venue, other_venue=other_venue, prod=prod)


def test_records_and_permissions():
    import access
    import auth
    import records

    fixtures()
    prod, people = STATE["prod"], STATE["people"]
    check("production: created with producer role",
          scalar("SELECT COUNT(*) FROM RoleAssignment WHERE production_id = %s "
                 "AND role_name = 'Producer'", (prod,)) == 1)
    before = scalar("SELECT COUNT(*) FROM Production")
    raises("production: rollback on bad producer id", Exception, records.create_production,
           "ZZ Broken", "Play", None, None, "Planning", PRODUCER_CLASSES, 999999)
    check("production: nothing left after rollback", scalar("SELECT COUNT(*) FROM Production") == before)
    raises("production: Cast cannot create", access.PermissionDenied, records.create_production,
           "ZZ No", "Play", None, None, "Planning", {"Cast / Crew"})
    check("records: update production", records.update_production(
        prod, "ZZ Test Production", "Play", None, None, "Rehearsal", PRODUCER_CLASSES) == 1)
    check("records: add person", records.add_person("ZZ Person", "zz.person@example.com", "1", ADMIN) == 1)
    raises("records: duplicate email blocked", access.RuleError, records.add_person,
           "ZZ Two", "ZZ.person@example.com", "2", ADMIN)
    pid = scalar("SELECT person_id FROM Person WHERE email = 'zz.person@example.com'")
    check("records: edit person", records.update_person(pid, "ZZ Person B", "zz.person@example.com", "9", ADMIN) == 1)
    check("records: delete unused person", records.delete_person(pid, ADMIN) == 1)
    raises("records: delete person with roles blocked", access.RuleError, records.delete_person, people[0], ADMIN)
    check("permission: finance approves expenses", access.can({"Finance"}, "approve_expense"))
    check("permission: stage manager cannot approve expenses",
          not access.can({"Stage Management"}, "approve_expense"))
    check("permission: viewer sees no budget", "Budget" not in access.visible_modules({"Viewer"}))
    check("permission: cast sees no accounts", "Accounts" not in access.visible_modules({"Cast / Crew"}))
    check("auth: account class overrides roles",
          auth.user_classes({"is_admin": False, "account_class": "Viewer"}, ["Producer"]) == {"Viewer"})
    check("auth: designer is department head",
          auth.user_classes({"is_admin": False, "account_class": None}, ["Set Designer"]) == {"Department Head"})


def test_schedule():
    import access
    import callsheets
    import resources
    import schedule

    prod, people, venue, other = STATE["prod"], STATE["people"], STATE["venue"], STATE["other_venue"]
    # A random far-future day, so repeated runs on the same copy do not clash.
    start = RUN_DAY.replace(hour=10)
    end = RUN_DAY.replace(hour=12)
    e1 = schedule.create_event(prod, venue, "Rehearsal", start, end, "Scheduled", "", [people[1], people[2]], classes=ADMIN)
    STATE["e1"] = e1
    raises("schedule: bad times", access.RuleError, schedule.create_event, prod, venue, "Rehearsal", end, start, classes=ADMIN)
    err = raises("schedule: venue clash needs confirm", access.ClashError, schedule.create_event,
                 prod, venue, "Production Meeting", start + timedelta(hours=1), end + timedelta(hours=1), classes=ADMIN)
    check("schedule: clash names the venue", err is not None and any(c["kind"] == "Venue" for c in err.clashes))
    err = raises("schedule: person clash needs confirm", access.ClashError, schedule.create_event,
                 prod, other, "Production Meeting", start, end, "Scheduled", "", [people[1]], classes=ADMIN)
    check("schedule: clash names the person", err is not None and any(c["kind"] == "Person" for c in err.clashes))
    e_back = schedule.create_event(prod, venue, "Production Meeting", end, end + timedelta(hours=1), classes=ADMIN)
    check("schedule: back-to-back is not a clash", e_back is not None)
    e2 = schedule.create_event(prod, venue, "Production Meeting", start, end, confirmed=True, classes=ADMIN)
    check("schedule: confirmed clash saves", e2 is not None)

    before = scalar("SELECT COUNT(*) FROM ProductionEvent")
    try:
        schedule.create_event(prod, other, "Production Meeting", start + timedelta(days=5),
                              end + timedelta(days=5), "Scheduled", "", [999999], classes=ADMIN)
    except Exception:  # noqa: BLE001
        pass
    check("schedule: rollback removes event when participant fails",
          scalar("SELECT COUNT(*) FROM ProductionEvent") == before)

    check("schedule: cancel event", schedule.set_event_status(e2, "Cancelled", classes=ADMIN) == 1)
    affected = schedule.affected_by_event(e1)
    check("schedule: affected list has people and venue",
          len(affected["people"]) == 2 and affected["venue"] == "ZZ Test Hall")
    check("schedule: reschedule to free slot", schedule.reschedule_event(
        e1, start + timedelta(days=1), end + timedelta(days=1), venue, classes=ADMIN) == 1)
    e4 = schedule.create_event(prod, venue, "Production Meeting", start, end, "Scheduled", "", [people[1]], classes=ADMIN)
    raises("schedule: reschedule into clash blocked", access.ClashError, schedule.reschedule_event,
           e1, start, end, venue, classes=ADMIN)
    check("schedule: reschedule confirmed", schedule.reschedule_event(e1, start, end, venue, confirmed=True, classes=ADMIN) == 1)
    raises("schedule: confirming a clashing event needs confirm", access.ClashError,
           schedule.set_event_status, e4, "Confirmed", classes=ADMIN)
    raises("schedule: add clashing participant needs confirm", access.ClashError,
           schedule.add_participant, e4, people[2], classes=ADMIN)
    check("schedule: add participant", schedule.add_participant(e4, people[3], classes=ADMIN) == 1)
    check("schedule: remove participant", schedule.remove_participant(e4, people[3], ADMIN) == 1)

    resources.add_resource("ZZ Spot Light", "Light", "Good", "Available", ADMIN)
    resources.add_resource("ZZ Broken Light", "Light", "Good", "Under Repair", ADMIN)
    good = scalar("SELECT resource_id FROM Resource WHERE resource_name = 'ZZ Spot Light'")
    bad = scalar("SELECT resource_id FROM Resource WHERE resource_name = 'ZZ Broken Light'")
    raises("reserve: under repair cannot be confirmed", access.RuleError, schedule.reserve_resource, e1, bad, classes=ADMIN)
    check("reserve: tentative on under repair allowed", schedule.reserve_resource(e1, bad, "Tentative", classes=ADMIN) == 1)
    check("reserve: confirm available resource", schedule.reserve_resource(e1, good, classes=ADMIN) == 1)
    raises("reserve: same resource overlapping event", access.ClashError, schedule.reserve_resource, e4, good, classes=ADMIN)

    s1 = callsheets.generate_call_sheet(e1, PRODUCER_CLASSES)
    s2 = callsheets.generate_call_sheet(e1, PRODUCER_CLASSES)
    revs = [r["revision_no"] for r in callsheets.list_call_sheets(prod) if r["event_id"] == e1]
    check("callsheet: numbered revisions", sorted(revs) == [1, 2], str(revs))
    raises("callsheet: draft cannot be acknowledged", access.RuleError, callsheets.acknowledge, s1, people[1], CAST)
    callsheets.issue_call_sheet(s1, PRODUCER_CLASSES)
    check("callsheet: issue supersedes older",
          callsheets.issue_call_sheet(s2, PRODUCER_CLASSES) == 1
          and scalar("SELECT status FROM CallSheet WHERE sheet_id = %s", (s1,)) == "Superseded")
    details = callsheets.sheet_details(s2)
    check("callsheet: details list people and resources",
          len(details["people"]) == 2 and len(details["resources"]) == 2)
    check("callsheet: acknowledge", callsheets.acknowledge(s2, people[1], CAST) == 1)
    raises("callsheet: non-recipient blocked", access.RuleError, callsheets.acknowledge, s2, people[0], CAST)
    missing = [r["full_name"] for r in callsheets.not_acknowledged(prod)]
    check("callsheet: one person has not acknowledged", len(missing) == 1, str(missing))
    check("callsheet: person's own sheets", len(callsheets.sheets_for_person(prod, people[1])) == 1)


def test_budget():
    import access
    import budget
    import team

    prod = STATE["prod"]
    team.add_department(prod, "ZZ Art", PRODUCER_CLASSES, "")
    raises("department: duplicate name blocked", access.RuleError, team.add_department, prod, "ZZ Art", PRODUCER_CLASSES)
    dept = team.list_departments(prod)[0]["department_id"]
    raises("budget: Cast cannot create", access.PermissionDenied, budget.create_budget_version,
           prod, {"Cast / Crew"})
    b1 = budget.create_budget_version(prod, {"Finance"})
    check("budget: add line", budget.add_line(b1, dept, "Paint", 1000, 800, FIN) == 1)
    line = budget.list_lines(b1)[0]["line_id"]
    check("budget: edit line", budget.update_line(line, 1000, 900, FIN) == 1)
    check("budget: approve", budget.approve_budget(b1, {"Producer"}) == 1)
    raises("budget: approved is read-only (add)", access.RuleError, budget.add_line, b1, dept, "Wood", 1, 1, FIN)
    raises("budget: approved is read-only (edit)", access.RuleError, budget.update_line, line, 1, 1, FIN)
    budget.create_budget_version(prod, {"Producer"})
    check("budget: version number increments", budget.list_budgets(prod)[0]["version_no"] == 2)
    check("budget: new version copies lines", len(budget.list_lines(budget.list_budgets(prod)[0]["budget_id"])) == 1)

    day = datetime(2031, 3, 1).date()
    ex, warning = budget.add_expense(line, "ZZ Vendor", day, 500, "", RES)
    check("expense: below 90 percent has no warning", warning is None)
    ex2, warning = budget.add_expense(line, "ZZ Vendor", day, 450, "", {"Finance"})
    check("expense: 95 percent warns near limit", warning == "near", str(warning))
    ex3, warning = budget.add_expense(line, "ZZ Vendor", day, 300, "", {"Finance"})
    check("expense: overspend warns", warning == "over", str(warning))
    raises("expense: Stage Manager cannot request", access.PermissionDenied, budget.add_expense,
           line, "x", day, 1, "", {"Stage Management"})
    raises("expense: Resource Coordinator cannot approve", access.PermissionDenied, budget.decide_expense,
           ex, "Approved", RES)
    raises("expense: Stage Manager cannot approve", access.PermissionDenied, budget.decide_expense,
           ex, "Approved", {"Stage Management"})
    budget.decide_expense(ex, "Approved", {"Finance"})
    budget.decide_expense(ex2, "Approved", {"Producer"})
    budget.decide_expense(ex3, "Rejected", {"Producer"})
    raises("expense: cannot decide twice", access.RuleError, budget.decide_expense, ex, "Approved", {"Finance"})
    lines = budget.list_lines(budget.list_budgets(prod)[1]["budget_id"])
    check("budget: actual counts approved only", lines[0]["actual"] == 950 and lines[0]["planned"] == 1000)
    check("budget: totals", budget.totals(lines)["difference"] == 50 and budget.totals(lines)["warning"] == "near")
    check("budget: expense list",
          len(budget.list_expenses(prod)) == 3 and len(budget.list_expenses(prod, "Rejected")) == 1)
    raises("budget: cannot delete line with expenses", access.RuleError, budget.delete_line, line, FIN)


def test_team_and_archive():
    import access
    import budget
    import callsheets
    import records
    import reports
    import schedule
    import team

    prod, people = STATE["prod"], STATE["people"]
    dept = team.list_departments(prod)[0]["department_id"]
    check("assignment: add", team.add_assignment(prod, people[1], "Actor", dept, None, None, PRODUCER_CLASSES) == 1)
    raises("assignment: bad dates", access.RuleError, team.add_assignment, prod, people[1], "Actor", dept,
           datetime(2031, 2, 1).date(), datetime(2031, 1, 1).date(), PRODUCER_CLASSES)
    aid = scalar("SELECT assignment_id FROM RoleAssignment WHERE production_id = %s "
                 "AND role_name = 'Actor'", (prod,))
    check("assignment: remove", team.remove_assignment(prod, aid, PRODUCER_CLASSES) == 1)
    check("task: add", team.add_task(prod, "ZZ Paint set", dept, None, datetime(2020, 1, 1).date(), "High", PRODUCER_CLASSES) == 1)
    task = team.list_tasks(prod)[0]["task_id"]
    check("task: assign", team.assign_task(prod, task, people[1], PRODUCER_CLASSES) == 1)
    check("task: overdue view", len(team.list_tasks(prod, overdue_only=True)) == 1)
    raises("task: Cast cannot change another person's task", access.PermissionDenied, team.set_task_status,
           prod, task, "Done", {"Cast / Crew"}, people[2])
    check("task: assignee updates own task",
          team.set_task_status(prod, task, "In Progress", {"Cast / Crew"}, people[1]) == 1)
    check("task: manager marks done", team.set_task_status(prod, task, "Done", {"Stage Management"}) == 1)
    check("task: done is not overdue", len(team.list_tasks(prod, overdue_only=True)) == 0)
    check("document: add", team.add_document(prod, "ZZ Script", "Script", "http://example.com", PRODUCER_CLASSES) == 1)
    doc = team.list_documents(prod)[0]["doc_id"]
    raises("document: Stage Manager cannot approve", access.PermissionDenied, team.decide_document,
           prod, doc, "Approved", {"Stage Management"})
    check("document: producer approves", team.decide_document(prod, doc, "Approved", {"Producer"}) == 1)
    check("document: producer rejects", team.decide_document(prod, doc, "Rejected", {"Producer"}) == 1)

    check("report: home queries run", isinstance(reports.events_this_week([prod]), list)
          and isinstance(reports.budget_alerts([prod]), list))
    check("report: csv export", reports.to_csv([{"a": 1, "b": "x"}]).startswith("a,b"))

    raises("archive: Cast cannot archive", access.PermissionDenied, records.archive_production,
           prod, {"Cast / Crew"})
    check("archive: producer archives", records.archive_production(prod, PRODUCER_CLASSES) == 1)
    start = RUN_DAY.replace(hour=10) + timedelta(days=400)
    hour = timedelta(hours=1)
    raises("archive: cannot add event", access.RuleError, schedule.create_event,
           prod, None, "Rehearsal", start, start + hour, classes=PRODUCER_CLASSES)
    raises("archive: cannot reschedule", access.RuleError, schedule.reschedule_event,
           STATE["e1"], start, start + hour, None, classes=PRODUCER_CLASSES)
    raises("archive: cannot add task", access.RuleError, team.add_task, prod, "x", None, None, None, "Low", PRODUCER_CLASSES)
    raises("archive: cannot add department", access.RuleError, team.add_department, prod, "ZZ Late", PRODUCER_CLASSES)
    raises("archive: cannot edit production", access.RuleError, records.update_production,
           prod, "x", "Play", None, None, "Planning", PRODUCER_CLASSES)
    raises("archive: cannot generate call sheet", access.RuleError, callsheets.generate_call_sheet, STATE["e1"], PRODUCER_CLASSES)
    old_line = budget.list_lines(budget.list_budgets(prod)[1]["budget_id"])[0]["line_id"]
    raises("archive: cannot add expense", access.RuleError, budget.add_expense,
           old_line, "x", start.date(), 5, "", {"Finance"})
    check("archive: history still readable", len(schedule.list_events(prod)) >= 4)


def test_every_page():
    """Open every module as every demo user with Streamlit's headless test runner."""
    from streamlit.testing.v1 import AppTest

    import auth
    import navigation
    import setup_auth
    from productions import productions_visible_to

    for login, password in setup_auth.demo_logins():
        account = auth.authenticate(login, password)
        check(f"login: {login}", account is not None)
        if account is None:
            continue
        productions = [p for p in productions_visible_to(account) if p["status"] != "Archived"]
        production = productions[0]
        classes = auth.user_classes(account, production["roles"])
        for page in navigation.page_names(classes, True):
            app = AppTest.from_file(str(Path(__file__).resolve().parent.parent / "app.py"), default_timeout=60)
            app.session_state["account"] = account
            app.session_state["production_id"] = production["production_id"]
            app.session_state["page"] = page
            app.run()
            problems = [e.value for e in app.exception]
            if not app.title:
                problems.append("page drew no title")
            check(f"page: {login} / {page}", not problems, "; ".join(problems)[:300])


def main():
    for test in (test_resources, test_records_and_permissions, test_schedule, test_budget,
                 test_team_and_archive, test_every_page):
        test()
    failed = [name for name, ok in results if not ok]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
