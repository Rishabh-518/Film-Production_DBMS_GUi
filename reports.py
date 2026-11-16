"""Dashboards per user class. The queries come from Lab 10A; the Q number is in each comment."""
import csv
import io

from access import ADMIN, CAST_CREW, DEPT_HEAD, FINANCE, PRODUCER, RESOURCE, STAGE, VIEWER
from db import transaction


def to_csv(rows):
    if not rows:
        return ""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def fetch(sql, params=()):
    with transaction() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def budget_summary(production_id):
    # Q29: the same totals as fn_budget_summary, written as a plain query so the app
    # does not depend on that function being installed.
    return fetch(
        """
        SELECT COALESCE(SUM(bl.planned_amount), 0) AS planned,
               COALESCE(SUM(bl.committed_amount), 0) AS committed,
               COALESCE((SELECT SUM(e.amount) FROM Expense e
                         JOIN BudgetLine x ON x.line_id = e.line_id
                         JOIN Budget bx ON bx.budget_id = x.budget_id
                         WHERE bx.production_id = %(p)s AND bx.status = 'Approved'
                           AND e.approval_status = 'Approved'), 0) AS actual
        FROM BudgetLine bl JOIN Budget b ON b.budget_id = bl.budget_id
        WHERE b.production_id = %(p)s AND b.status = 'Approved'
        """,
        {"p": production_id},
    )


def upcoming_events(production_id):
    # Q10: events that are still only scheduled.
    return fetch(
        """
        SELECT event_id, event_type, start_datetime, end_datetime, status
        FROM ProductionEvent
        WHERE production_id = %s AND status IN ('Scheduled', 'Confirmed')
          AND start_datetime >= NOW()
        ORDER BY start_datetime LIMIT 20
        """,
        (production_id,),
    )


def open_high_priority_tasks(production_id):
    # Q7: high-priority tasks that are not finished.
    return fetch(
        "SELECT task_id, title, due_date, status FROM Task "
        "WHERE production_id = %s AND priority = 'High' AND status <> 'Done' ORDER BY due_date",
        (production_id,),
    )


def overdue_tasks(production_id):
    # Q23: past due date and not done.
    return fetch(
        """
        SELECT d.department_name, t.title AS task, t.priority, t.due_date, t.status,
               COALESCE(per.full_name, 'Unassigned') AS responsible
        FROM Task t
        LEFT JOIN Department d ON d.department_id = t.department_id
        LEFT JOIN Person per ON per.person_id = t.person_id
        WHERE t.production_id = %s AND t.due_date < CURRENT_DATE AND t.status <> 'Done'
        ORDER BY t.due_date
        """,
        (production_id,),
    )


def resource_clashes():
    # Q16: the same resource reserved for two overlapping events.
    return fetch(
        """
        SELECT r.resource_name, r1.event_id AS event_a, r2.event_id AS event_b,
               e1.start_datetime AS a_start, e2.start_datetime AS b_start
        FROM EventResourceReservation r1
        JOIN EventResourceReservation r2 ON r2.resource_id = r1.resource_id AND r2.event_id > r1.event_id
        JOIN ProductionEvent e1 ON e1.event_id = r1.event_id
        JOIN ProductionEvent e2 ON e2.event_id = r2.event_id
        JOIN Resource r ON r.resource_id = r1.resource_id
        WHERE r1.reservation_status <> 'Cancelled' AND r2.reservation_status <> 'Cancelled'
          AND e1.start_datetime < e2.end_datetime AND e2.start_datetime < e1.end_datetime
        LIMIT 50
        """
    )


def available_resources():
    # Q3: available and in good condition.
    return fetch(
        "SELECT resource_id, resource_name, resource_type FROM Resource "
        "WHERE status = 'Available' AND resource_condition = 'Good' "
        "ORDER BY resource_type, resource_name LIMIT 50"
    )


def resource_status_counts():
    # Q6 grouped by status: how many resources are in each state.
    return fetch("SELECT status, COUNT(*) AS resources FROM Resource GROUP BY status ORDER BY status")


def expense_status_summary():
    # Q9: count and totals by approval status.
    return fetch(
        """
        SELECT approval_status, COUNT(*) AS expenses, SUM(amount) AS total_amount,
               MAX(amount) AS largest_amount
        FROM Expense GROUP BY approval_status ORDER BY total_amount DESC
        """
    )


def lines_over_commitment(production_id):
    # Q15: spent (approved and pending) is more than committed.
    return fetch(
        """
        SELECT d.department_name, bl.category, bl.committed_amount,
               SUM(e.amount) AS spent, SUM(e.amount) - bl.committed_amount AS over_by
        FROM BudgetLine bl
        JOIN Budget b ON b.budget_id = bl.budget_id
        LEFT JOIN Department d ON d.department_id = bl.department_id
        JOIN Expense e ON e.line_id = bl.line_id
        WHERE b.production_id = %s AND e.approval_status <> 'Rejected'
        GROUP BY bl.line_id, d.department_name, bl.category, bl.committed_amount
        HAVING SUM(e.amount) > bl.committed_amount
        ORDER BY over_by DESC
        """,
        (production_id,),
    )


def archived_history():
    # Q28: archived productions with the history that was kept.
    return fetch(
        """
        SELECT p.title, p.end_date,
               (SELECT COUNT(*) FROM ProductionEvent pe WHERE pe.production_id = p.production_id) AS events,
               (SELECT COUNT(*) FROM Document d WHERE d.production_id = p.production_id) AS documents,
               (SELECT COALESCE(SUM(e.amount), 0) FROM Expense e
                JOIN BudgetLine bl ON bl.line_id = e.line_id
                JOIN Budget b ON b.budget_id = bl.budget_id
                WHERE b.production_id = p.production_id) AS total_spent
        FROM Production p WHERE p.status = 'Archived' ORDER BY p.end_date
        """
    )


def my_events(production_id, person_id):
    return fetch(
        """
        SELECT e.event_type, e.start_datetime, e.end_datetime, v.venue_name, ep.participation_status
        FROM EventParticipation ep
        JOIN ProductionEvent e ON e.event_id = ep.event_id
        LEFT JOIN Venue v ON v.venue_id = e.venue_id
        WHERE ep.person_id = %s AND e.production_id = %s AND e.status IS DISTINCT FROM 'Cancelled'
        ORDER BY e.start_datetime
        """,
        (person_id, production_id),
    )


def my_tasks(production_id, person_id):
    return fetch(
        "SELECT title, priority, due_date, status FROM Task "
        "WHERE person_id = %s AND production_id = %s ORDER BY due_date",
        (person_id, production_id),
    )


def pending_call_sheet_acks(production_id):
    # Like Q21: who was sent a call sheet and has not acknowledged.
    return fetch(
        """
        SELECT per.full_name, e.event_type, cs.call_date, cs.revision_no
        FROM CallSheet cs
        JOIN ProductionEvent e ON e.event_id = cs.event_id
        JOIN EventParticipation ep ON ep.event_id = e.event_id
        JOIN Person per ON per.person_id = ep.person_id
        WHERE e.production_id = %s AND cs.status = 'Issued'
          AND NOT EXISTS (SELECT 1 FROM CallSheetAcknowledgement a
                          WHERE a.sheet_id = cs.sheet_id AND a.person_id = ep.person_id)
        ORDER BY cs.call_date, per.full_name LIMIT 50
        """,
        (production_id,),
    )


# ---- Home page queries -------------------------------------------------------
# Each takes the production ids the user may see (or a person id) and returns rows.
# Rows keep production_id so the screen can open that production.

def status_counts(ids):
    return fetch(
        "SELECT status, COUNT(*) AS productions FROM Production "
        "WHERE production_id = ANY(%s) GROUP BY status ORDER BY productions DESC",
        (ids,),
    )


def events_this_week(ids):
    return fetch(
        """
        SELECT p.production_id, p.title AS production, e.event_type AS event,
               e.start_datetime AS starts, v.venue_name AS venue, e.status
        FROM ProductionEvent e
        JOIN Production p ON p.production_id = e.production_id
        LEFT JOIN Venue v ON v.venue_id = e.venue_id
        WHERE e.production_id = ANY(%s) AND e.status IS DISTINCT FROM 'Cancelled'
          AND e.start_datetime >= CURRENT_DATE AND e.start_datetime < CURRENT_DATE + 8
        ORDER BY e.start_datetime LIMIT 100
        """,
        (ids,),
    )


def event_clashes(ids):
    # Same overlap rule as schedule.find_clashes and Q16, for events from today on.
    return fetch(
        """
        WITH ev AS (
            SELECT event_id, production_id, venue_id, event_type,
                   start_datetime AS s, end_datetime AS f
            FROM ProductionEvent
            WHERE status IS DISTINCT FROM 'Cancelled' AND end_datetime >= CURRENT_DATE
        ), pairs AS (
            SELECT a.event_id AS a_id, b.event_id AS b_id, a.production_id, a.s AS starts,
                   a.venue_id AS a_venue, b.venue_id AS b_venue
            FROM ev a JOIN ev b ON b.event_id > a.event_id AND a.s < b.f AND b.s < a.f
            WHERE a.production_id = ANY(%(ids)s)
        )
        SELECT x.production_id, p.title AS production, x.kind, x.what, x.starts
        FROM (
            SELECT 'Venue' AS kind, v.venue_name AS what, pr.production_id, pr.starts
            FROM pairs pr JOIN Venue v ON v.venue_id = pr.a_venue
            WHERE pr.a_venue = pr.b_venue
            UNION ALL
            SELECT 'Person', per.full_name, pr.production_id, pr.starts
            FROM pairs pr
            JOIN EventParticipation p1 ON p1.event_id = pr.a_id
            JOIN EventParticipation p2 ON p2.event_id = pr.b_id AND p2.person_id = p1.person_id
            JOIN Person per ON per.person_id = p1.person_id
            UNION ALL
            SELECT 'Resource', r.resource_name, pr.production_id, pr.starts
            FROM pairs pr
            JOIN EventResourceReservation r1 ON r1.event_id = pr.a_id
                 AND r1.reservation_status <> 'Cancelled'
            JOIN EventResourceReservation r2 ON r2.event_id = pr.b_id
                 AND r2.resource_id = r1.resource_id AND r2.reservation_status <> 'Cancelled'
            JOIN Resource r ON r.resource_id = r1.resource_id
        ) x JOIN Production p ON p.production_id = x.production_id
        ORDER BY x.starts LIMIT 50
        """,
        {"ids": ids},
    )


def damaged_resources():
    return fetch(
        "SELECT resource_name, resource_type, status, resource_condition FROM Resource "
        "WHERE status IN ('Damaged', 'Under Repair') "
        "OR resource_condition IN ('Damaged', 'Under Repair') ORDER BY resource_name LIMIT 100"
    )


def pending_expenses(ids):
    return fetch(
        """
        SELECT p.production_id, p.title AS production, d.department_name AS department,
               bl.category, e.vendor, e.amount, e.expense_date
        FROM Expense e
        JOIN BudgetLine bl ON bl.line_id = e.line_id
        JOIN Budget b ON b.budget_id = bl.budget_id
        JOIN Production p ON p.production_id = b.production_id
        LEFT JOIN Department d ON d.department_id = bl.department_id
        WHERE b.production_id = ANY(%s) AND e.approval_status = 'Pending'
        ORDER BY e.expense_date LIMIT 100
        """,
        (ids,),
    )


def pending_documents(ids):
    return fetch(
        """
        SELECT p.production_id, p.title AS production, d.title AS document,
               d.doc_type, d.version_no
        FROM Document d JOIN Production p ON p.production_id = d.production_id
        WHERE d.production_id = ANY(%s) AND d.approval_status = 'Pending'
        ORDER BY p.title, d.title LIMIT 100
        """,
        (ids,),
    )


def budget_alerts(ids):
    # Lines of the approved budget where approved spending reached 90% of planned.
    return fetch(
        """
        SELECT p.production_id, p.title AS production, d.department_name AS department,
               bl.category, bl.planned_amount AS planned,
               COALESCE(SUM(e.amount) FILTER (WHERE e.approval_status = 'Approved'), 0) AS spent,
               ROUND(100 * SUM(e.amount) FILTER (WHERE e.approval_status = 'Approved')
                     / bl.planned_amount) AS percent_used
        FROM BudgetLine bl
        JOIN Budget b ON b.budget_id = bl.budget_id AND b.status = 'Approved'
        JOIN Production p ON p.production_id = b.production_id
        LEFT JOIN Department d ON d.department_id = bl.department_id
        LEFT JOIN Expense e ON e.line_id = bl.line_id
        WHERE b.production_id = ANY(%s) AND bl.planned_amount > 0
        GROUP BY p.production_id, p.title, d.department_name, bl.line_id,
                 bl.category, bl.planned_amount
        HAVING COALESCE(SUM(e.amount) FILTER (WHERE e.approval_status = 'Approved'), 0)
               >= 0.9 * bl.planned_amount
        ORDER BY percent_used DESC LIMIT 50
        """,
        (ids,),
    )


def unacknowledged_sheets(ids):
    # Like Q21, summed per call sheet, for the next 7 days.
    return fetch(
        """
        SELECT p.production_id, p.title AS production, e.event_type AS event,
               cs.call_date, cs.revision_no AS revision, COUNT(*) AS not_acknowledged
        FROM CallSheet cs
        JOIN ProductionEvent e ON e.event_id = cs.event_id
        JOIN Production p ON p.production_id = e.production_id
        JOIN EventParticipation ep ON ep.event_id = e.event_id
        WHERE e.production_id = ANY(%s) AND cs.status = 'Issued'
          AND cs.call_date BETWEEN CURRENT_DATE AND CURRENT_DATE + 7
          AND NOT EXISTS (SELECT 1 FROM CallSheetAcknowledgement a
                          WHERE a.sheet_id = cs.sheet_id AND a.person_id = ep.person_id)
        GROUP BY p.production_id, p.title, e.event_id, e.event_type, cs.sheet_id,
                 cs.call_date, cs.revision_no
        ORDER BY cs.call_date LIMIT 100
        """,
        (ids,),
    )


def overdue_tasks_in(ids):
    # Q23 across several productions.
    return fetch(
        """
        SELECT p.production_id, p.title AS production, t.title AS task, t.priority,
               t.due_date, t.status
        FROM Task t JOIN Production p ON p.production_id = t.production_id
        WHERE t.production_id = ANY(%s) AND t.due_date < CURRENT_DATE AND t.status <> 'Done'
        ORDER BY t.due_date LIMIT 100
        """,
        (ids,),
    )


def department_tasks(person_id, ids):
    # Open tasks of the departments this person works in.
    return fetch(
        """
        SELECT p.production_id, p.title AS production, d.department_name AS department,
               t.title AS task, t.priority, t.due_date, t.status
        FROM Task t
        JOIN Production p ON p.production_id = t.production_id
        JOIN Department d ON d.department_id = t.department_id
        WHERE t.production_id = ANY(%(ids)s) AND t.status <> 'Done'
          AND t.department_id IN (SELECT department_id FROM RoleAssignment
                                  WHERE person_id = %(person)s AND department_id IS NOT NULL)
        ORDER BY t.due_date LIMIT 100
        """,
        {"ids": ids, "person": person_id},
    )


def next_calls(person_id, ids):
    return fetch(
        """
        SELECT p.production_id, p.title AS production, e.event_type AS event,
               e.start_datetime AS starts, v.venue_name AS venue
        FROM EventParticipation ep
        JOIN ProductionEvent e ON e.event_id = ep.event_id
        JOIN Production p ON p.production_id = e.production_id
        LEFT JOIN Venue v ON v.venue_id = e.venue_id
        WHERE ep.person_id = %s AND e.production_id = ANY(%s)
          AND e.status IS DISTINCT FROM 'Cancelled' AND e.start_datetime >= CURRENT_DATE
        ORDER BY e.start_datetime LIMIT 20
        """,
        (person_id, ids),
    )


def sheets_to_acknowledge(person_id, ids):
    return fetch(
        """
        SELECT p.production_id, p.title AS production, e.event_type AS event,
               cs.call_date, cs.reporting_time, cs.revision_no AS revision
        FROM EventParticipation ep
        JOIN ProductionEvent e ON e.event_id = ep.event_id
        JOIN Production p ON p.production_id = e.production_id
        JOIN CallSheet cs ON cs.event_id = e.event_id AND cs.status = 'Issued'
        WHERE ep.person_id = %s AND e.production_id = ANY(%s) AND cs.call_date >= CURRENT_DATE
          AND NOT EXISTS (SELECT 1 FROM CallSheetAcknowledgement a
                          WHERE a.sheet_id = cs.sheet_id AND a.person_id = ep.person_id)
        ORDER BY cs.call_date LIMIT 20
        """,
        (person_id, ids),
    )


def open_tasks_of(person_id, ids):
    return fetch(
        """
        SELECT p.production_id, p.title AS production, t.title AS task, t.priority,
               t.due_date, t.status
        FROM Task t JOIN Production p ON p.production_id = t.production_id
        WHERE t.person_id = %s AND t.production_id = ANY(%s) AND t.status <> 'Done'
        ORDER BY t.due_date LIMIT 50
        """,
        (person_id, ids),
    )
