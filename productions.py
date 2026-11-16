from db import transaction


def all_productions():
    with transaction() as cur:
        cur.execute(
            """
            SELECT production_id, title, production_type, start_date, end_date, status,
                   ARRAY[]::VARCHAR[] AS roles
            FROM Production
            ORDER BY title
            """
        )
        return cur.fetchall()


def productions_for_person(person_id):
    with transaction() as cur:
        cur.execute(
            """
            SELECT p.production_id, p.title, p.production_type, p.start_date, p.end_date,
                   p.status, array_agg(DISTINCT ra.role_name) AS roles
            FROM Production p
            JOIN RoleAssignment ra ON ra.production_id = p.production_id
            WHERE ra.person_id = %s
            GROUP BY p.production_id
            ORDER BY p.title
            """,
            (person_id,),
        )
        return cur.fetchall()


def productions_visible_to(account):
    if account["is_admin"] or account["account_class"]:
        return all_productions()
    return productions_for_person(account["person_id"])


def filter_productions(productions, search, status, production_type):
    search = search.strip().lower()
    return [
        p
        for p in productions
        if search in p["title"].lower()
        and status in ("All", p["status"])
        and production_type in ("All", p["production_type"])
    ]


def production_summary(production_id):
    with transaction() as cur:
        cur.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM Department
                 WHERE production_id = %(id)s) AS departments,
                (SELECT COUNT(DISTINCT person_id) FROM RoleAssignment
                 WHERE production_id = %(id)s) AS people,
                (SELECT COUNT(*) FROM ProductionEvent
                 WHERE production_id = %(id)s) AS events,
                (SELECT COUNT(*) FROM ProductionEvent
                 WHERE production_id = %(id)s
                   AND start_datetime >= NOW()
                   AND status IS DISTINCT FROM 'Cancelled') AS upcoming_events,
                (SELECT COUNT(*) FROM Task
                 WHERE production_id = %(id)s
                   AND status IS DISTINCT FROM 'Done') AS open_tasks,
                (SELECT COUNT(*) FROM Document
                 WHERE production_id = %(id)s) AS documents
            """,
            {"id": production_id},
        )
        return cur.fetchone()


def is_current(production):
    return production["status"] not in ("Archived", "Completed")


def current_first(productions, show_all):
    """Active productions by start date; with show_all the finished ones follow."""
    chosen = [p for p in productions if show_all or is_current(p)]
    return sorted(chosen, key=lambda p: (not is_current(p), p["start_date"] or p["end_date"]))
