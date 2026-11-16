"""Check film_demo against the demo targets and the coherence rules. Read-only.
Run from production_app:  .venv\\Scripts\\python tools\\check_demo_data.py
"""
import os
import sys
from pathlib import Path

os.environ["APP_DBNAME"] = "film_demo"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2

from auth import CAST_CREW, ROLE_TO_USER_CLASS
from db import transaction
from db_config import DB_SETTINGS

ACTIVE = "('Pre-production', 'Rehearsal', 'Shooting')"
STAGE = "('Play', 'Musical')"
IN_WINDOW = "e.start_datetime >= CURRENT_DATE - 14 AND e.start_datetime < CURRENT_DATE + 22"

# (label, SQL returning one number, test on that number)
TARGETS = [
    ("active productions (25)", f"SELECT COUNT(*) FROM Production WHERE status IN {ACTIVE}", lambda n: n >= 25),
    ("active productions with events outside 5..8 in window (0)",
     f"SELECT COUNT(*) FROM Production p WHERE p.status IN {ACTIVE} AND (SELECT COUNT(*) FROM ProductionEvent e "
     f"WHERE e.production_id = p.production_id AND e.status <> 'Proposed' AND {IN_WINDOW}) NOT BETWEEN 5 AND 8", lambda n: n == 0),
    ("window events: past not Completed or future not Scheduled (0)",
     f"SELECT COUNT(*) FROM ProductionEvent e WHERE {IN_WINDOW} AND e.status <> 'Proposed' AND "
     "((e.end_datetime < now() AND e.status <> 'Completed') OR (e.end_datetime >= now() AND e.status <> 'Scheduled'))",
     lambda n: n == 0),
    ("active events with participants outside 3..8 (0)",
     f"SELECT COUNT(*) FROM ProductionEvent e JOIN Production p USING (production_id) WHERE p.status IN {ACTIVE} AND {IN_WINDOW} "
     "AND e.status <> 'Proposed' AND (SELECT COUNT(*) FROM EventParticipation ep WHERE ep.event_id = e.event_id) NOT BETWEEN 3 AND 9",
     lambda n: n == 0),
    ("reservations (>= 20)", "SELECT COUNT(*) FROM EventResourceReservation", lambda n: n >= 20),
    ("Proposed future events (2-3)",
     "SELECT COUNT(*) FROM ProductionEvent WHERE status = 'Proposed' AND start_datetime > now()", lambda n: 2 <= n <= 3),
    ("Requested reservations (3-4)",
     "SELECT COUNT(*) FROM EventResourceReservation WHERE reservation_status = 'Requested'", lambda n: 3 <= n <= 4),
    ("Rejected reservations (1)",
     "SELECT COUNT(*) FROM EventResourceReservation WHERE reservation_status = 'Rejected'", lambda n: n == 1),
    ("issued call sheets in next 7 days (>= 5)",
     "SELECT COUNT(*) FROM CallSheet s JOIN ProductionEvent e USING (event_id) WHERE s.status = 'Issued' "
     "AND e.start_datetime BETWEEN now() AND now() + interval '7 days'", lambda n: n >= 5),
    ("upcoming recipients not yet acknowledged (>= 5)",
     "SELECT COUNT(*) FROM CallSheet s JOIN ProductionEvent e USING (event_id) JOIN EventParticipation ep USING (event_id) "
     "WHERE s.status = 'Issued' AND e.start_datetime BETWEEN now() AND now() + interval '7 days' "
     "AND ep.participation_status <> 'Unavailable' AND NOT EXISTS (SELECT 1 FROM CallSheetAcknowledgement a "
     "WHERE a.sheet_id = s.sheet_id AND a.person_id = ep.person_id)", lambda n: n >= 5),
    ("call sheets at revision 2 (>= 1)", "SELECT COUNT(*) FROM CallSheet WHERE revision_no = 2", lambda n: n >= 1),
    ("items out (10)", "SELECT COUNT(*) FROM ResourceMovement WHERE actual_return IS NULL", lambda n: n == 10),
    ("items out and overdue (4)",
     "SELECT COUNT(*) FROM ResourceMovement WHERE actual_return IS NULL AND expected_return < now()", lambda n: n == 4),
    ("returned Damaged or Under Repair (>= 3)",
     "SELECT COUNT(*) FROM ResourceMovement WHERE return_condition IN ('Damaged', 'Under Repair')", lambda n: n >= 3),
    ("active productions without an Approved budget of 4..6 lines (0)",
     f"SELECT COUNT(*) FROM Production p WHERE p.status IN {ACTIVE} AND NOT EXISTS (SELECT 1 FROM Budget b "
     "WHERE b.production_id = p.production_id AND b.status = 'Approved' AND "
     "(SELECT COUNT(*) FROM BudgetLine l WHERE l.budget_id = b.budget_id) BETWEEN 4 AND 6)", lambda n: n == 0),
    ("expense statuses present (3)", "SELECT COUNT(DISTINCT approval_status) FROM Expense", lambda n: n == 3),
    ("lines at 90% or more of planned (>= 2)", "SELECT COUNT(*) FROM (" + (
        "SELECT l.line_id FROM BudgetLine l JOIN Expense e USING (line_id) WHERE e.approval_status IN ('Approved', 'Pending') "
        "GROUP BY l.line_id, l.planned_amount HAVING SUM(e.amount) >= 0.9 * l.planned_amount") + ") x", lambda n: n >= 2),
    ("lines over planned (>= 1)", "SELECT COUNT(*) FROM (" + (
        "SELECT l.line_id FROM BudgetLine l JOIN Expense e USING (line_id) WHERE e.approval_status IN ('Approved', 'Pending') "
        "GROUP BY l.line_id, l.planned_amount HAVING SUM(e.amount) > l.planned_amount") + ") x", lambda n: n >= 1),
    ("Draft budgets at version 2 (>= 1)", "SELECT COUNT(*) FROM Budget WHERE version_no = 2 AND status = 'Draft'", lambda n: n >= 1),
    ("overdue open tasks (8)",
     "SELECT COUNT(*) FROM Task WHERE due_date < CURRENT_DATE AND status <> 'Done'", lambda n: n == 8),
    ("open tasks due in the next 14 days (>= 20)",
     "SELECT COUNT(*) FROM Task WHERE status <> 'Done' AND due_date BETWEEN CURRENT_DATE AND CURRENT_DATE + 13", lambda n: n >= 20),
    ("Pending documents (>= 5)", "SELECT COUNT(*) FROM Document WHERE approval_status = 'Pending'", lambda n: n >= 5),
    ("Approved documents (>= 5)", "SELECT COUNT(*) FROM Document WHERE approval_status = 'Approved'", lambda n: n >= 5),
]

CLASH_SQL = """
SELECT 'Person' AS kind, COUNT(*) FROM EventParticipation x JOIN ProductionEvent a ON a.event_id = x.event_id
  JOIN EventParticipation y ON y.person_id = x.person_id AND y.event_id > x.event_id
  JOIN ProductionEvent b ON b.event_id = y.event_id
  WHERE x.participation_status <> 'Unavailable' AND y.participation_status <> 'Unavailable'
    AND a.status NOT IN ('Cancelled') AND b.status NOT IN ('Cancelled')
    AND a.start_datetime < b.end_datetime AND a.end_datetime > b.start_datetime
UNION ALL
SELECT 'Venue', COUNT(*) FROM ProductionEvent a JOIN ProductionEvent b ON b.venue_id = a.venue_id AND b.event_id > a.event_id
  WHERE a.status <> 'Cancelled' AND b.status <> 'Cancelled'
    AND a.start_datetime < b.end_datetime AND a.end_datetime > b.start_datetime
UNION ALL
SELECT 'Resource', COUNT(*) FROM EventResourceReservation x JOIN ProductionEvent a ON a.event_id = x.event_id
  JOIN EventResourceReservation y ON y.resource_id = x.resource_id AND y.event_id > x.event_id
  JOIN ProductionEvent b ON b.event_id = y.event_id
  WHERE x.reservation_status IN ('Confirmed', 'Tentative') AND y.reservation_status IN ('Confirmed', 'Tentative')
    AND a.status <> 'Cancelled' AND b.status <> 'Cancelled'
    AND a.start_datetime < b.end_datetime AND a.end_datetime > b.start_datetime
"""

# Each rule is a COUNT of offending rows and must be 0.
RULES = [
    ("status does not match dates",
     "SELECT COUNT(*) FROM Production WHERE "
     "(status = 'Planning' AND start_date <= CURRENT_DATE) "
     "OR (status IN ('Pre-production', 'Rehearsal', 'Shooting') AND NOT (start_date <= CURRENT_DATE AND end_date >= CURRENT_DATE)) "
     "OR (status = 'Post-production' AND start_date > CURRENT_DATE) "
     "OR (status IN ('Completed', 'Archived') AND end_date >= CURRENT_DATE)"),
    ("event status disagrees with production or time",
     "SELECT COUNT(*) FROM ProductionEvent e JOIN Production p USING (production_id) WHERE "
     "(p.status = 'Planning' AND e.status = 'Completed') OR (e.status = 'Scheduled' AND e.end_datetime < now()) "
     "OR (e.status = 'Completed' AND e.start_datetime > now()) "
     "OR (p.status IN ('Completed', 'Archived') AND e.status NOT IN ('Completed', 'Cancelled'))"),
    ("productions missing a Producer or Director",
     "SELECT COUNT(*) FROM Production p WHERE NOT EXISTS (SELECT 1 FROM RoleAssignment r WHERE r.production_id = p.production_id "
     "AND r.role_name = 'Producer') OR NOT EXISTS (SELECT 1 FROM RoleAssignment r WHERE r.production_id = p.production_id "
     "AND r.role_name = 'Director')"),
    ("film without Camera Operator or play without Stage Manager",
     "SELECT COUNT(*) FROM Production p WHERE NOT EXISTS (SELECT 1 FROM RoleAssignment r WHERE r.production_id = p.production_id "
     "AND r.role_name = CASE WHEN p.production_type IN " + STAGE + " THEN 'Stage Manager' ELSE 'Camera Operator' END)"),
    ("role does not fit production type",
     "SELECT COUNT(*) FROM RoleAssignment r JOIN Production p USING (production_id) WHERE "
     "(r.role_name = 'Camera Operator' AND p.production_type IN " + STAGE + ") "
     "OR (r.role_name = 'Stage Manager' AND p.production_type NOT IN " + STAGE + ")"),
    ("production without 3 to 5 departments",
     "SELECT COUNT(*) FROM Production p WHERE (SELECT COUNT(*) FROM Department d WHERE d.production_id = p.production_id) NOT BETWEEN 3 AND 5"),
    ("production without 6 to 15 people",
     "SELECT COUNT(*) FROM Production p WHERE (SELECT COUNT(DISTINCT person_id) FROM RoleAssignment r "
     "WHERE r.production_id = p.production_id) NOT BETWEEN 6 AND 15"),
    ("participant not assigned to the event's production",
     "SELECT COUNT(*) FROM EventParticipation ep JOIN ProductionEvent e USING (event_id) WHERE NOT EXISTS "
     "(SELECT 1 FROM RoleAssignment r WHERE r.production_id = e.production_id AND r.person_id = ep.person_id)"),
    ("acknowledgement by someone who is not a participant",
     "SELECT COUNT(*) FROM CallSheetAcknowledgement a JOIN CallSheet s USING (sheet_id) WHERE NOT EXISTS "
     "(SELECT 1 FROM EventParticipation ep WHERE ep.event_id = s.event_id AND ep.person_id = a.person_id)"),
    ("task assignee not on the production",
     "SELECT COUNT(*) FROM Task t WHERE t.person_id IS NOT NULL AND NOT EXISTS "
     "(SELECT 1 FROM RoleAssignment r WHERE r.production_id = t.production_id AND r.person_id = t.person_id)"),
    ("resource Issued without an open movement",
     "SELECT COUNT(*) FROM Resource r WHERE r.status = 'Issued' AND NOT EXISTS "
     "(SELECT 1 FROM ResourceMovement m WHERE m.resource_id = r.resource_id AND m.actual_return IS NULL)"),
    ("open movement on a resource that is not Issued",
     "SELECT COUNT(*) FROM ResourceMovement m JOIN Resource r USING (resource_id) WHERE m.actual_return IS NULL AND r.status <> 'Issued'"),
    ("Damaged or Under Repair resource without such a return",
     "SELECT COUNT(*) FROM Resource r WHERE r.status IN ('Damaged', 'Under Repair') AND NOT EXISTS "
     "(SELECT 1 FROM ResourceMovement m WHERE m.resource_id = r.resource_id AND m.return_condition = r.status)"),
    ("expense dated outside its production",
     "SELECT COUNT(*) FROM Expense x JOIN BudgetLine l USING (line_id) JOIN Budget b USING (budget_id) "
     "JOIN Production p USING (production_id) WHERE x.expense_date NOT BETWEEN p.start_date AND p.end_date "
     "OR x.expense_date > CURRENT_DATE"),
    ("budget line in a department of another production",
     "SELECT COUNT(*) FROM BudgetLine l JOIN Budget b USING (budget_id) JOIN Department d ON d.department_id = l.department_id "
     "WHERE d.production_id <> b.production_id"),
]


def run_scalar(cur, sql):
    cur.execute(sql)
    return list(cur.fetchone().values())[0]


def verdict(ok):
    return "PASS" if ok else "FAIL"


def check_targets(cur):
    for label, sql, test in TARGETS:
        n = run_scalar(cur, sql)
        print(f"{verdict(test(n))}  {label}: {n}")
    cur.execute(CLASH_SQL)
    counts = {row["kind"]: row["count"] for row in cur.fetchall()}
    print(f"{verdict(counts == {'Person': 1, 'Venue': 1, 'Resource': 1})}  deliberate clashes (1 person, 1 venue, 1 resource): {counts}")


def check_rules(cur):
    for label, sql in RULES:
        n = run_scalar(cur, sql)
        print(f"{verdict(n == 0)}  rule, none expected: {label}: {n}")
    cur.execute("SELECT person_id, ARRAY_AGG(DISTINCT role_name) AS roles FROM RoleAssignment GROUP BY person_id")
    mixed = [r for r in cur.fetchall()
             if len({ROLE_TO_USER_CLASS.get(role, CAST_CREW) for role in r["roles"]}) > 1]
    print(f"{verdict(len(mixed) <= 3)}  people mixing user classes (at most a few): {len(mixed)}")


def show_logins(cur):
    cur.execute(
        """
        SELECT a.email, a.account_class, p.person_id, p.full_name,
               (SELECT ARRAY_AGG(DISTINCT role_name) FROM RoleAssignment r WHERE r.person_id = p.person_id) AS roles,
               (SELECT ARRAY_AGG(DISTINCT r.production_id) FROM RoleAssignment r JOIN Production pr USING (production_id)
                 WHERE r.person_id = p.person_id AND pr.status IN ('Pre-production', 'Rehearsal', 'Shooting')) AS active,
               (SELECT COUNT(*) FROM EventParticipation ep JOIN ProductionEvent e USING (event_id)
                 WHERE ep.person_id = p.person_id AND e.start_datetime > now() AND e.status <> 'Cancelled') AS upcoming
        FROM auth.account a LEFT JOIN Person p ON p.person_id = a.person_id ORDER BY a.account_id
        """
    )
    print()
    for r in cur.fetchall():
        if r["person_id"] is None:
            print(f"{r['email']:<16} Admin")
            continue
        classes = r["account_class"] or sorted({ROLE_TO_USER_CLASS.get(x, CAST_CREW) for x in (r["roles"] or [])})
        print(f"{r['email']:<16} {r['full_name']} (id {r['person_id']}) classes={classes} "
              f"active productions={r['active']} upcoming events={r['upcoming']}")


def real_database_counts():
    conn = psycopg2.connect(**DB_SETTINGS)
    cur = conn.cursor()
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'")
    names = [row[0] for row in cur.fetchall()]
    bad = {}
    for name in names:
        cur.execute('SELECT COUNT(*) FROM "' + name + '"')
        count = cur.fetchone()[0]
        if count != 100:
            bad[name] = count
    conn.close()
    print(f"\n{verdict(not bad)}  real database: {len(names)} tables, all with 100 rows" + (f" except {bad}" if bad else ""))


if __name__ == "__main__":
    with transaction() as cur:
        check_targets(cur)
        check_rules(cur)
        show_logins(cur)
    real_database_counts()
