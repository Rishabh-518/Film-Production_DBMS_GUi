"""Rebuild the film_demo database with coherent demo data. Safe to run again.

film_demo starts as a copy of the real database (so Person, Venue, Resource and
the auth schema come along). Every production table is then emptied and refilled
around today's date. The real database is only ever read.
Run from production_app:  .venv\\Scripts\\python tools\\seed_demo.py
"""
import itertools
import os
import subprocess
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

# Must be set before db.py is imported, so nothing here can touch the real database.
os.environ["APP_DBNAME"] = "film_demo"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2
from psycopg2.extras import execute_values

import setup_auth
from db import SETTINGS, transaction
from db_config import DB_SETTINGS

PG_BIN = r"C:\Program Files\PostgreSQL\18\bin"
TODAY = date.today()
NOW = datetime.now().replace(microsecond=0)

STAGE_TYPES = ("Play", "Musical")
DEPTS_FILM = ["Direction", "Camera", "Art", "Sound", "Costume"]
DEPTS_STAGE = ["Direction", "Lighting", "Costume", "Sound", "Art"]
DESIGNER_ROLE = {"Art": "Set Designer", "Costume": "Costume Designer", "Lighting": "Lighting Designer",
                 "Sound": "Sound Engineer", "Camera": "Camera Operator"}
EVENTS_FILM = ["Production Meeting", "Location Visit", "Shoot Day", "Editing Milestone", "Screening", "Audition"]
EVENTS_STAGE = ["Production Meeting", "Audition", "Rehearsal", "Technical Rehearsal", "Performance"]
CATEGORIES = ["Costumes", "Set Build", "Transport", "Salaries", "Equipment", "Venue Hire", "Marketing", "Catering"]
VENDORS = ["Northgate Supplies", "Lumen Hire Co", "Riverside Catering", "Stagecraft Ltd", "City Transport", "PrintWorks"]
TASK_TITLES = ["Confirm venue access", "Finalise props list", "Order costumes", "Book rehearsal room",
               "Review script changes", "Test lighting plot", "Collect permits", "Update call times",
               "Check sound equipment", "Approve set drawings"]
DOC_TYPES = ["Contract", "Script", "Technical Note", "Permission", "Schedule", "Receipt"]

# Each person belongs to one user class for the whole database, so nobody mixes classes.
PRODUCERS = list(range(9, 19))
DIRECTORS = list(range(19, 29))
STAGE_POOL = list(range(29, 39))
FINANCE = list(range(39, 47))
DESIGN = list(range(47, 61))
CREW = list(range(61, 101))
POOLS = {"producer": PRODUCERS, "director": DIRECTORS, "stage": STAGE_POOL,
         "finance": FINANCE, "design": DESIGN, "crew": CREW}
# The first four productions are plays, so every demo login has a role that fits.
DEMO_PEOPLE = {"Producer": 1, "Director": 2, "Stage Manager": 3, "Costume Designer": 4,
               "Finance Manager": 5, "Actor": 6}
BUSY_PRODUCTIONS = 4
ACTIVE_COUNT = 25

USED_SLOTS = set()
IDS = {name: itertools.count(1) for name in
       ["dept", "role", "event", "sheet", "budget", "line", "expense", "task", "doc", "movement"]}


def day(offset):
    return TODAY + timedelta(days=offset)


def copy_database():
    conn = psycopg2.connect(**{**DB_SETTINGS, "dbname": "postgres"})
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = 'film_demo' AND pid <> pg_backend_pid()")
    cur.execute("DROP DATABASE IF EXISTS film_demo")
    try:
        cur.execute('CREATE DATABASE film_demo TEMPLATE "Film production project"')
    except psycopg2.Error:
        cur.execute("CREATE DATABASE film_demo")
        dump_and_restore()
    conn.close()


def dump_and_restore():
    """Fallback when the real database has other connections and cannot be a template."""
    env = {**os.environ, "PGPASSWORD": DB_SETTINGS["password"]}
    target = ["-h", DB_SETTINGS["host"], "-p", str(DB_SETTINGS["port"]), "-U", DB_SETTINGS["user"]]
    dump = subprocess.Popen([PG_BIN + r"\pg_dump.exe", *target, "Film production project"],
                            stdout=subprocess.PIPE, env=env)
    subprocess.run([PG_BIN + r"\psql.exe", *target, "-q", "-d", "film_demo"],
                   stdin=dump.stdout, env=env, check=True, stdout=subprocess.DEVNULL)


def clear_production_tables(cur):
    for table in ["CallSheetAcknowledgement", "CallSheet", "EventParticipation", "EventResourceReservation",
                  "ResourceMovement", "Expense", "BudgetLine", "Budget", "Task", "Document",
                  "RoleAssignment", "ProductionEvent", "Department", "Production"]:
        # Whole-table delete on purpose: this is the demo database being rebuilt.
        cur.execute("TRUNCATE " + table + " CASCADE")


def free_slot(d, slot):
    """Events never overlap each other, except the deliberate clashes made later."""
    while (d, slot) in USED_SLOTS:
        slot += 1
        if slot == 6:
            slot, d = 0, d + timedelta(days=1)
    USED_SLOTS.add((d, slot))
    return d, slot


# ---------- productions, departments, crew ----------

def production_plan(p, title, ptype):
    if p <= BUSY_PRODUCTIONS:
        ptype = "Play" if p % 2 else "Musical"
    stage = ptype in STAGE_TYPES
    if p <= ACTIVE_COUNT:
        status = "Pre-production" if p % 3 == 0 else ("Rehearsal" if stage else "Shooting")
        start, end = day(-(20 + p % 15)), day(30 + p % 25)
    elif p <= 40:
        status, start = "Planning", day(25 + p % 40)
        end = start + timedelta(days=60 + p % 30)
    elif p <= 55:
        status, start, end = "Post-production", day(-120 - p % 30), day(10 + p % 30)
    elif p <= 80:
        status, end = "Completed", day(-20 - p % 100)
        start = end - timedelta(days=60 + p % 30)
    else:
        status, end = "Archived", day(-150 - p % 60)
        start = end - timedelta(days=60 + p % 30)
    return {"id": p, "title": title, "type": ptype, "stage": stage, "status": status,
            "start": start, "end": end, "active": p <= ACTIVE_COUNT}


def pick(pool, p, used, key):
    k = used.get(key, 0)
    used[key] = k + 1
    return POOLS[pool][(p * 3 + k) % len(POOLS[pool])]


def crew_for(prod):
    """A list of (person_id, role, department name) that fits the production type."""
    p, stage = prod["id"], prod["stage"]
    depts = DEPTS_STAGE if stage else DEPTS_FILM
    depts = depts[:3 + p % 3]
    plan = [("Producer", "", "producer"), ("Director", "Direction", "director"),
            ("Assistant Director", "Direction", "stage"), ("Finance Manager", "", "finance")]
    plan.append(("Stage Manager", "", "stage") if stage else ("Camera Operator", "Camera", "crew"))
    for name in depts:
        if name in DESIGNER_ROLE:
            plan.append((DESIGNER_ROLE[name], name, "crew" if name == "Camera" else "design"))
    plan += [("Actor", "", "crew")] * (2 + p % 4) + [("Makeup Artist", "", "crew")]
    if p % 2 == 0 and len(plan) < 15:
        plan.append(("Writer", "", "crew"))
    used, crew, demo_done = {}, [], set()
    for role, dept, pool in plan:
        person = pick(pool, p, used, pool)
        if p <= BUSY_PRODUCTIONS and role in DEMO_PEOPLE and role not in demo_done:
            person = DEMO_PEOPLE[role]
            demo_done.add(role)
        crew.append((person, role, dept))
    return depts, crew


# ---------- events ----------

def new_event(p, etype, d, slot, status=None):
    d, slot = free_slot(d, slot)
    event_id = next(IDS["event"])
    start = datetime.combine(d, time(8 + 2 * slot))
    if status is None:
        status = "Completed" if start + timedelta(minutes=90) < NOW else "Scheduled"
    return {"id": event_id, "p": p, "venue": (event_id * 7) % 100 + 1, "type": etype, "start": start,
            "end": start + timedelta(minutes=90), "status": status, "notes": "Demo schedule"}


def events_for(prod):
    p, types = prod["id"], (EVENTS_STAGE if prod["stage"] else EVENTS_FILM)
    if prod["active"]:
        count = 8 if p <= BUSY_PRODUCTIONS else 5 + p % 4
        events = []
        for j in range(count):
            index = j * ACTIVE_COUNT + p - 1
            events.append(new_event(p, types[(p + j) % len(types)], day(-14 + index // 6), index % 6))
        return events
    if prod["status"] == "Planning":
        return [new_event(p, "Production Meeting", prod["start"] + timedelta(days=3), p % 6),
                new_event(p, "Audition", prod["start"] + timedelta(days=10), p % 6)]
    if prod["status"] == "Post-production":
        kind = "Editing Milestone" if not prod["stage"] else "Performance"
        return [new_event(p, kind, day(-20 - p % 30), p % 6), new_event(p, "Screening" if not prod["stage"] else "Production Meeting",
                                                                         day(-40 - p % 20), p % 6)]
    span = (prod["end"] - prod["start"]).days
    events = [new_event(p, types[(p + i) % len(types)], prod["start"] + timedelta(days=span * (i + 1) // 4), p % 6, "Completed")
              for i in range(3)]
    if p % 7 == 0:
        events[2]["status"] = "Cancelled"
    return events


def participants_for(event, people):
    """3 to 8 people from the production's own crew."""
    count = 3 + event["id"] % 6
    shift = event["id"] % len(people)
    chosen = (people[shift:] + people[:shift])[:count]
    if event["p"] <= BUSY_PRODUCTIONS:
        demo = [2, 3, 6]
        chosen = demo + [x for x in chosen if x not in demo][:count - 3]
    rows = []
    for i, person in enumerate(chosen):
        if event["start"] < NOW:
            status = "Absent" if (event["id"] + i) % 7 == 0 else "Present"
        else:
            status = "Unavailable" if event["p"] > BUSY_PRODUCTIONS and (event["id"] + i) % 9 == 0 else "Assigned"
        rows.append([person, status])
    return rows


def pick_pair(candidates, parts, used):
    """Two future events of different productions with no person in common."""
    for a in candidates:
        for b in candidates:
            if a["id"] >= b["id"] or a["p"] == b["p"] or a["id"] in used or b["id"] in used:
                continue
            if a["venue"] == b["venue"] or {x for x, _ in parts[a["id"]]} & {x for x, _ in parts[b["id"]]}:
                continue
            used.update([a["id"], b["id"]])
            return a, b
    raise RuntimeError("no event pair for a clash")


def overlap(a, b):
    """Move b so it starts 30 minutes into a. It ends exactly when the next slot starts."""
    b["start"] = a["start"] + timedelta(minutes=30)
    b["end"] = b["start"] + timedelta(minutes=90)


def make_clashes(events, parts, reservations, crews):
    """Exactly three: a person, a venue and a resource double-booked."""
    soon = [e for e in events if e["p"] > BUSY_PRODUCTIONS and e["p"] <= ACTIVE_COUNT and e["status"] == "Scheduled"
            and NOW + timedelta(days=2) < e["start"] < NOW + timedelta(days=18)]
    used = set()
    with_crew = [e for e in soon if any(x in CREW for x, _ in parts[e["id"]])]
    a, b = pick_pair(with_crew, parts, used)  # person
    overlap(a, b)
    shared = next(x for x, _ in parts[a["id"]] if x in CREW)
    parts[b["id"]].append([shared, "Assigned"])
    for row in parts[a["id"]]:
        if row[0] == shared:
            row[1] = "Assigned"
    if shared not in [x for x, _, _ in crews[b["p"]]]:
        crews[b["p"]].append((shared, "Actor", ""))
    a, b = pick_pair(soon, parts, used)  # venue
    overlap(a, b)
    b["venue"] = a["venue"]
    a, b = pick_pair(soon, parts, used)  # resource
    overlap(a, b)
    for event in (a, b):
        reservations.append((event["id"], 99, event["start"] - timedelta(days=7), "Confirmed"))
    return {"person": (a, b)}


# ---------- budgets, tasks, documents ----------

NEAR = {(1, 0): (0.85, 0.08), (2, 1): (0.88, 0.05), (5, 0): (0.85, 0.08), (10, 0): (0.88, 0.05)}
OVER = {(3, 0): (0.95, 0.12), (4, 2): (1.02, 0.03)}


def money(x):
    return max(100, round(x / 10) * 10)


def expenses_for_line(prod, k, planned, line_id):
    """Approved, pending and rejected expenses, all dated inside the production."""
    p = prod["id"]
    f, g = NEAR.get((p, k)) or OVER.get((p, k)) or (0.25 + ((p + k) % 5) * 0.1, 0.05 + ((p * k) % 3) * 0.03)
    if not prod["active"]:
        f, g = 0.4 + ((p + k) % 4) * 0.1, 0
    parts = [("Approved", 0.6 * f), ("Approved", 0.4 * f), ("Rejected", 0.04)]
    if g:
        parts.append(("Pending", g))
    if prod["active"] and k % 3 == 2:
        parts = parts[:2] + parts[3:]
    last = min(prod["end"], TODAY)
    span = (last - prod["start"]).days
    rows = []
    for i, (status, share) in enumerate(parts):
        when = prod["start"] + timedelta(days=(p * 13 + i * 17 + k * 5) % (span + 1))
        rows.append((next(IDS["expense"]), line_id, VENDORS[(p + i + k) % 6], when, money(planned * share),
                     status, "https://receipts.example.org/" + str(p) + "-" + str(k) + "-" + str(i)))
    return rows


def budget_for(prod, dept_ids, out):
    p = prod["id"]
    planning = prod["status"] == "Planning"
    count = 4 + p % 3 if prod["active"] else 3 + p % 2
    budget_id = next(IDS["budget"])
    out["budget"].append((budget_id, p, 1, prod["start"], "Draft" if planning else "Approved"))
    lines = []
    for k in range(count):
        planned = (15 + (p * 7 + k * 11) % 30) * 1000
        committed = 0 if planning else round(planned * (0.5 + ((p + k) % 4) * 0.1))
        line_id = next(IDS["line"])
        lines.append((line_id, budget_id, dept_ids[k % len(dept_ids)], CATEGORIES[(k + p) % 8], planned, committed))
        if not planning:
            out["expense"] += expenses_for_line(prod, k, planned, line_id)
    out["line"] += lines
    if p <= 3:
        draft_id = next(IDS["budget"])
        out["budget"].append((draft_id, p, 2, TODAY, "Draft"))
        for line in lines[:3]:
            out["line"].append((next(IDS["line"]), draft_id, line[2], line[3], round(line[4] * 1.1), 0))


def tasks_for(prod, dept_ids, people, state, out):
    p = prod["id"]
    if prod["active"]:
        for t in range(10 if p <= BUSY_PRODUCTIONS else 6):
            bucket = (p + t) % 6
            if bucket == 0 and state["overdue"] < 7:
                state["overdue"] += 1
                due, status = day(-(1 + t % 9)), ("Open", "In Progress")[t % 2]
            elif bucket in (3, 4):
                due, status = day(7 + t % 7), "Open"
            elif bucket == 5:
                due, status = day(-(3 + t)), "Done"
            else:
                due, status = day(t % 7), ("Open", "In Progress")[t % 2]
            add_task(out, p, dept_ids, people, t, due, status)
        return
    if prod["status"] == "Planning":
        specs = [(prod["start"] + timedelta(days=4), "Open"), (prod["start"] + timedelta(days=12), "Open")]
    elif prod["status"] == "Post-production":
        specs = [(day(-30 - p % 20), "Done"), (day(5 + p % 10), "In Progress")]
    else:
        specs = [(prod["start"] + timedelta(days=20), "Done"), (prod["end"] - timedelta(days=5), "Done")]
    for t, (due, status) in enumerate(specs):
        add_task(out, p, dept_ids, people, t, due, status)


def actor_tasks_for(prod, out):
    """The demo actor login gets one task due this week, one next week and one overdue."""
    p = prod["id"]
    if p > 3:
        return
    due = (day(3), day(10), day(-2))[p - 1]
    dept = prod["dept_ids"][0]
    out["task"].append((next(IDS["task"]), p, dept, DEMO_PEOPLE["Actor"], TASK_TITLES[(p + 4) % 10], due,
                        "High", "Open"))


def add_task(out, p, dept_ids, people, t, due, status):
    out["task"].append((next(IDS["task"]), p, dept_ids[t % len(dept_ids)], people[(t * 3 + p) % len(people)],
                        TASK_TITLES[(p + t) % 10], due, ("High", "Medium", "Low")[(p + t) % 3], status))


def documents_for(prod, out):
    p = prod["id"]
    if prod["active"]:
        statuses = ["Pending", "Approved", "Pending" if p % 2 else "Draft"]
    elif prod["status"] == "Planning":
        statuses = ["Draft", "Pending"]
    else:
        statuses = ["Approved", "Approved"]
    for i, status in enumerate(statuses):
        doc_id = next(IDS["doc"])
        out["doc"].append((doc_id, p, prod["title"] + " " + DOC_TYPES[(p + i) % 6].lower(), DOC_TYPES[(p + i) % 6],
                           "https://docs.example.org/" + str(doc_id), 1 + i % 2, status))


# ---------- call sheets, resources ----------

def call_sheets(events, parts, out):
    """Sheets for active-production events: past ones fully acknowledged, the next 7 days partly."""
    revision_two_done = False
    for event in events:
        if event["p"] > ACTIVE_COUNT or event["status"] in ("Cancelled", "Proposed"):
            continue
        people = [x for x, status in parts[event["id"]] if status != "Unavailable"]
        upcoming = NOW < event["start"] <= NOW + timedelta(days=7)
        if event["start"] > NOW and not upcoming:
            continue
        revisions = [1]
        if upcoming and event["p"] <= BUSY_PRODUCTIONS and not revision_two_done:
            revisions, revision_two_done = [1, 2], True
        for revision in revisions:
            sheet_id = next(IDS["sheet"])
            status = "Superseded" if revision < revisions[-1] else "Issued"
            out["sheet"].append((sheet_id, event["id"], event["start"].date(),
                                 (event["start"] - timedelta(hours=1)).time(), revision, status))
            if status != "Issued":
                continue
            if upcoming:
                acked = [x for i, x in enumerate(people) if i % 2 == 0 and x != 6]
            else:
                acked = [x for x, s in parts[event["id"]] if s == "Present"]
            out["ack"] += [(sheet_id, x, event["start"] - timedelta(days=1)) for x in acked]


def movements(out):
    """About 10 items out (4 overdue), some returned fine, and four returned damaged."""
    status, rows = {}, []
    for i in range(10):
        resource = 61 + i
        expected = NOW - timedelta(days=1 + i) if i < 4 else NOW + timedelta(days=2 + i)
        rows.append((next(IDS["movement"]), resource, CREW[i], NOW - timedelta(days=6), expected, None, None))
        status[resource] = "Issued"
    for i in range(10):
        issued = NOW - timedelta(days=30 + i)
        rows.append((next(IDS["movement"]), 71 + i, CREW[10 + i], issued, issued + timedelta(days=5),
                     issued + timedelta(days=4), ("Good", "Fair")[i % 2]))
        status[71 + i] = "Returned"
    for i, condition in enumerate(["Damaged", "Damaged", "Under Repair", "Under Repair"]):
        issued = NOW - timedelta(days=15 + i)
        rows.append((next(IDS["movement"]), 81 + i, CREW[20 + i], issued, issued + timedelta(days=3),
                     issued + timedelta(days=3), condition))
        status[81 + i] = condition
    out["movement"] = rows
    return status


# ---------- build everything in memory, then insert ----------

def build(titles):
    out = {k: [] for k in ["production", "dept", "role", "event", "part", "reserve", "sheet", "ack",
                           "budget", "line", "expense", "task", "doc", "movement"]}
    events, parts, crews, state = [], {}, {}, {"overdue": 0}
    for p, (title, ptype) in enumerate(titles, start=1):
        prod = production_plan(p, title, ptype)
        out["production"].append((p, title, prod["type"], prod["start"], prod["end"], prod["status"]))
        names, crew = crew_for(prod)
        dept_ids = {}
        for name in names:
            dept_ids[name] = next(IDS["dept"])
            out["dept"].append((dept_ids[name], p, name, name + " department"))
        crews[p] = crew
        prod_events = events_for(prod)
        if p <= 3:
            prod_events.append(new_event(p, "Rehearsal", day(23 + p), p, "Proposed"))
        events += prod_events
        people = [person for person, _, _ in crew]
        for event in prod_events:
            if event["status"] != "Cancelled":
                parts[event["id"]] = participants_for(event, people)
        prod["dept_ids"] = list(dept_ids.values())
        prod["dept_map"] = dept_ids
        budget_for(prod, prod["dept_ids"], out)
        tasks_for(prod, prod["dept_ids"], people, state, out)
        actor_tasks_for(prod, out)
        documents_for(prod, out)
        crews[p] = crew
        out.setdefault("prods", {})[p] = prod
    reservations = reserve_resources(events)
    reservations += request_resources(events)
    make_clashes(events, parts, reservations, crews)
    for p, crew in crews.items():
        prod = out["prods"][p]
        for person, role, dept in crew:
            out["role"].append((next(IDS["role"]), p, prod["dept_map"].get(dept), person, role, prod["start"],
                                prod["end"], 300 + person % 9 * 150))
    for event in events:
        out["event"].append((event["id"], event["p"], event["venue"], event["type"], event["start"],
                             event["end"], event["status"], event["notes"]))
        out["part"] += [(event["id"], person, status) for person, status in parts.get(event["id"], [])]
    out["reserve"] = reservations
    call_sheets(events, parts, out)
    return out, movements(out)


def reserve_resources(events):
    """Resources 1 to 60 go to alternate active events; they never overlap in time."""
    rows, k = [], 0
    for event in sorted(events, key=lambda e: e["start"]):
        if event["p"] > ACTIVE_COUNT or event["status"] in ("Cancelled", "Proposed") or event["id"] % 2 or k >= 60:
            continue
        future = event["start"] > NOW
        status = "Cancelled" if k % 11 == 10 else ("Tentative" if future and k % 5 == 4 else "Confirmed")
        rows.append((event["id"], 1 + k, event["start"] - timedelta(days=7), status))
        k += 1
    return rows


def request_resources(events):
    """Requested and Rejected reservations never count as clashes."""
    later = sorted((e for e in events if e["status"] == "Scheduled" and e["start"] > NOW + timedelta(days=1)),
                   key=lambda e: e["start"])
    mine = [e for e in later if e["p"] <= BUSY_PRODUCTIONS]
    others = [e for e in later if BUSY_PRODUCTIONS < e["p"] <= ACTIVE_COUNT]
    chosen = [(mine[0], 85, "Requested"), (mine[3], 86, "Requested"), (mine[6], 87, "Requested"),
              (others[0], 88, "Requested"), (mine[9], 89, "Rejected")]
    return [(e["id"], resource, e["start"] - timedelta(days=5), status) for e, resource, status in chosen]


def insert(cur, table, columns, rows):
    execute_values(cur, "INSERT INTO " + table + " (" + columns + ") VALUES %s", rows)


def save(cur, out, resource_status):
    insert(cur, "Production", "production_id, title, production_type, start_date, end_date, status", out["production"])
    insert(cur, "Department", "department_id, production_id, department_name, description", out["dept"])
    insert(cur, "RoleAssignment", "assignment_id, production_id, department_id, person_id, role_name, "
           "start_date, end_date, payment_rate", out["role"])
    insert(cur, "ProductionEvent", "event_id, production_id, venue_id, event_type, start_datetime, "
           "end_datetime, status, hosting_notes", out["event"])
    insert(cur, "EventParticipation", "event_id, person_id, participation_status", out["part"])
    insert(cur, "EventResourceReservation", "event_id, resource_id, reserved_at, reservation_status", out["reserve"])
    insert(cur, "CallSheet", "sheet_id, event_id, call_date, reporting_time, revision_no, status", out["sheet"])
    insert(cur, "CallSheetAcknowledgement", "sheet_id, person_id, acknowledged_at", out["ack"])
    insert(cur, "Budget", "budget_id, production_id, version_no, effective_date, status", out["budget"])
    insert(cur, "BudgetLine", "line_id, budget_id, department_id, category, planned_amount, committed_amount", out["line"])
    insert(cur, "Expense", "expense_id, line_id, vendor, expense_date, amount, approval_status, receipt_link", out["expense"])
    insert(cur, "Task", "task_id, production_id, department_id, person_id, title, due_date, priority, status", out["task"])
    insert(cur, "Document", "doc_id, production_id, title, doc_type, storage_link, version_no, approval_status", out["doc"])
    insert(cur, "ResourceMovement", "movement_id, resource_id, person_id, issue_datetime, expected_return, "
           "actual_return, return_condition", out["movement"])
    set_resource_statuses(cur, resource_status)


def set_resource_statuses(cur, resource_status):
    cur.execute("UPDATE Resource SET status = 'Available' WHERE resource_id > 0")
    for resource_id, status in resource_status.items():
        cur.execute("UPDATE Resource SET status = %s WHERE resource_id = %s", (status, resource_id))
        if status in ("Damaged", "Under Repair"):
            cur.execute("UPDATE Resource SET resource_condition = %s WHERE resource_id = %s", (status, resource_id))
    cur.execute(
        """
        UPDATE Resource SET status = 'Reserved'
        WHERE status = 'Available' AND resource_id IN (
            SELECT r.resource_id FROM EventResourceReservation r
            JOIN ProductionEvent e ON e.event_id = r.event_id
            WHERE r.reservation_status IN ('Confirmed', 'Tentative') AND e.status NOT IN ('Cancelled', 'Proposed')
              AND e.start_datetime > now())
        """
    )


def main():
    assert SETTINGS["dbname"] == "film_demo", "refusing to seed anything but film_demo"
    copy_database()
    with transaction() as cur:
        cur.execute("SELECT title, production_type FROM Production ORDER BY production_id")
        titles = [(row["title"], row["production_type"]) for row in cur.fetchall()]
        out, resource_status = build(titles)
        clear_production_tables(cur)
        save(cur, out, resource_status)
    for login, password, who in setup_auth.set_up_accounts():
        print(f"{login:<36} {password:<20} {who}")
    print("film_demo is ready. Run tools\\check_demo_data.py to verify it.")


if __name__ == "__main__":
    main()
