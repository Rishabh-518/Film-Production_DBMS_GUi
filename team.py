"""Departments, role assignments, tasks and documents of one production."""
from psycopg2.errors import ForeignKeyViolation, UniqueViolation

from access import RuleError, check_production_open, require, sees_all_departments
from db import transaction

TASK_STATUSES = ["Open", "In Progress", "Done"]
PRIORITIES = ["High", "Medium", "Low"]
DOCUMENT_TYPES = ["Contract", "Permission", "Receipt", "Schedule", "Script", "Technical Note"]
DOCUMENT_STATUSES = ["Draft", "Pending", "Approved", "Rejected"]


def list_departments(production_id):
    with transaction() as cur:
        cur.execute(
            "SELECT department_id, department_name, description FROM Department "
            "WHERE production_id = %s ORDER BY department_name",
            (production_id,),
        )
        return cur.fetchall()


def own_department_ids(cur, production_id, person_id):
    """Departments this person works in on this production (their RoleAssignment rows)."""
    cur.execute(
        "SELECT DISTINCT department_id FROM RoleAssignment "
        "WHERE production_id = %s AND person_id = %s AND department_id IS NOT NULL",
        (production_id, person_id),
    )
    return [row["department_id"] for row in cur.fetchall()]


def departments_for(production_id, classes, person_id):
    """The departments a user may manage: all of them, or a Department Head's own."""
    departments = list_departments(production_id)
    if sees_all_departments(classes):
        return departments
    with transaction() as cur:
        own = own_department_ids(cur, production_id, person_id)
    return [d for d in departments if d["department_id"] in own]


def check_department_scope(cur, classes, production_id, acting_person_id, department_id):
    """A Department Head may only touch rows of their own departments (SRS section 9)."""
    if sees_all_departments(classes):
        return
    if department_id not in own_department_ids(cur, production_id, acting_person_id):
        raise RuleError("A Department Head can only manage their own department.")


def add_department(production_id, name, classes, description=""):
    require(classes, "manage_departments")
    if not name.strip():
        raise RuleError("A department needs a name.")
    try:
        with transaction() as cur:
            check_production_open(cur, production_id)
            cur.execute(
                """
                INSERT INTO Department (department_id, production_id, department_name, description)
                SELECT COALESCE(MAX(department_id), 0) + 1, %s, %s, %s FROM Department
                """,
                (production_id, name.strip(), description),
            )
            return cur.rowcount
    except UniqueViolation:
        raise RuleError("This production already has a department with that name.") from None


def delete_department(production_id, department_id, classes):
    require(classes, "manage_departments")
    try:
        with transaction() as cur:
            check_production_open(cur, production_id)
            cur.execute(
                "DELETE FROM Department WHERE department_id = %s AND production_id = %s",
                (department_id, production_id),
            )
            return cur.rowcount
    except ForeignKeyViolation:
        raise RuleError(
            "This department has roles, tasks or budget lines, so it can't be deleted."
        ) from None


def list_assignments(production_id):
    with transaction() as cur:
        cur.execute(
            """
            SELECT ra.assignment_id, per.full_name, ra.role_name, d.department_name,
                   ra.start_date, ra.end_date
            FROM RoleAssignment ra
            JOIN Person per ON per.person_id = ra.person_id
            LEFT JOIN Department d ON d.department_id = ra.department_id
            WHERE ra.production_id = %s
            ORDER BY per.full_name, ra.role_name
            """,
            (production_id,),
        )
        return cur.fetchall()


def role_names():
    """Role names are data (SRS 5.1), so the list comes from what is already used."""
    with transaction() as cur:
        cur.execute("SELECT DISTINCT role_name FROM RoleAssignment ORDER BY role_name")
        return [row["role_name"] for row in cur.fetchall()]


def add_assignment(production_id, person_id, role_name, department_id, start_date, end_date,
                   classes, acting_person_id=None, payment_rate=None):
    require(classes, "manage_assignments")
    if not role_name.strip():
        raise RuleError("A role assignment needs a role name.")
    if start_date and end_date and end_date < start_date:
        raise RuleError("The end date cannot be before the start date.")
    with transaction() as cur:
        check_production_open(cur, production_id)
        check_department_scope(cur, classes, production_id, acting_person_id, department_id)
        cur.execute(
            """
            INSERT INTO RoleAssignment (assignment_id, production_id, department_id, person_id,
                                        role_name, start_date, end_date, payment_rate)
            SELECT COALESCE(MAX(assignment_id), 0) + 1, %s, %s, %s, %s, %s, %s, %s
            FROM RoleAssignment
            """,
            (production_id, department_id, person_id, role_name.strip(), start_date, end_date,
             payment_rate),
        )
        return cur.rowcount


def remove_assignment(production_id, assignment_id, classes, acting_person_id=None):
    require(classes, "manage_assignments")
    with transaction() as cur:
        check_production_open(cur, production_id)
        cur.execute(
            "SELECT department_id FROM RoleAssignment WHERE assignment_id = %s AND production_id = %s",
            (assignment_id, production_id),
        )
        assignment = cur.fetchone()
        if assignment is None:
            raise RuleError("That role assignment does not exist.")
        check_department_scope(
            cur, classes, production_id, acting_person_id, assignment["department_id"]
        )
        cur.execute(
            "DELETE FROM RoleAssignment WHERE assignment_id = %s AND production_id = %s",
            (assignment_id, production_id),
        )
        return cur.rowcount


def list_tasks(production_id, status="All", person_id=None, overdue_only=False):
    with transaction() as cur:
        cur.execute(
            """
            SELECT t.task_id, t.title, d.department_name, per.full_name AS responsible,
                   t.person_id, t.priority, t.due_date, t.status
            FROM Task t
            LEFT JOIN Department d ON d.department_id = t.department_id
            LEFT JOIN Person per ON per.person_id = t.person_id
            WHERE t.production_id = %s
              AND (%s = 'All' OR t.status = %s)
              AND (%s::INT IS NULL OR t.person_id = %s::INT)
              AND (NOT %s OR (t.due_date < CURRENT_DATE AND t.status <> 'Done'))
            ORDER BY t.due_date
            """,
            (production_id, status, status, person_id, person_id, overdue_only),
        )
        return cur.fetchall()


def add_task(production_id, title, department_id, person_id, due_date, priority, classes,
             acting_person_id=None):
    require(classes, "manage_tasks")
    if not title.strip():
        raise RuleError("A task needs a title.")
    with transaction() as cur:
        check_production_open(cur, production_id)
        check_department_scope(cur, classes, production_id, acting_person_id, department_id)
        cur.execute(
            """
            INSERT INTO Task (task_id, production_id, department_id, person_id, title,
                              due_date, priority, status)
            SELECT COALESCE(MAX(task_id), 0) + 1, %s, %s, %s, %s, %s, %s, 'Open' FROM Task
            """,
            (production_id, department_id, person_id, title.strip(), due_date, priority),
        )
        return cur.rowcount


def assign_task(production_id, task_id, person_id, classes, acting_person_id=None):
    require(classes, "manage_tasks")
    with transaction() as cur:
        check_production_open(cur, production_id)
        cur.execute(
            "SELECT department_id FROM Task WHERE task_id = %s AND production_id = %s",
            (task_id, production_id),
        )
        task = cur.fetchone()
        if task is None:
            raise RuleError("That task does not exist.")
        check_department_scope(cur, classes, production_id, acting_person_id, task["department_id"])
        cur.execute(
            "UPDATE Task SET person_id = %s WHERE task_id = %s AND production_id = %s",
            (person_id, task_id, production_id),
        )
        return cur.rowcount


def set_task_status(production_id, task_id, status, classes, acting_person_id=None):
    """Managers change any task. Cast and crew may only update tasks given to them."""
    with transaction() as cur:
        check_production_open(cur, production_id)
        cur.execute(
            "SELECT person_id, department_id FROM Task WHERE task_id = %s AND production_id = %s",
            (task_id, production_id),
        )
        task = cur.fetchone()
        if task is None:
            raise RuleError("That task does not exist.")
        own_task = acting_person_id is not None and task["person_id"] == acting_person_id
        if not own_task:
            require(classes, "manage_tasks")
            check_department_scope(
                cur, classes, production_id, acting_person_id, task["department_id"]
            )
        cur.execute(
            "UPDATE Task SET status = %s WHERE task_id = %s AND production_id = %s",
            (status, task_id, production_id),
        )
        return cur.rowcount


def list_documents(production_id, status="All"):
    with transaction() as cur:
        cur.execute(
            """
            SELECT doc_id, title, doc_type, version_no, approval_status, storage_link
            FROM Document
            WHERE production_id = %s AND (%s = 'All' OR approval_status = %s)
            ORDER BY title, version_no DESC
            """,
            (production_id, status, status),
        )
        return cur.fetchall()


def add_document(production_id, title, doc_type, storage_link, classes, version_no=1):
    """New documents start as Pending so someone with approval rights reviews them."""
    require(classes, "manage_documents")
    if not title.strip():
        raise RuleError("A document needs a title.")
    with transaction() as cur:
        check_production_open(cur, production_id)
        cur.execute(
            """
            INSERT INTO Document (doc_id, production_id, title, doc_type, storage_link,
                                  version_no, approval_status)
            SELECT COALESCE(MAX(doc_id), 0) + 1, %s, %s, %s, %s, %s, 'Pending' FROM Document
            """,
            (production_id, title.strip(), doc_type, storage_link.strip(), version_no),
        )
        return cur.rowcount


def decide_document(production_id, doc_id, decision, classes):
    require(classes, "approve_document")
    if decision not in ("Approved", "Rejected"):
        raise RuleError("The decision must be Approved or Rejected.")
    with transaction() as cur:
        check_production_open(cur, production_id)
        cur.execute(
            "SELECT approval_status FROM Document WHERE doc_id = %s AND production_id = %s",
            (doc_id, production_id),
        )
        document = cur.fetchone()
        if document is None:
            raise RuleError("That document does not exist.")
        if document["approval_status"] == decision:
            raise RuleError(f"This document is already {decision}.")
        cur.execute(
            "UPDATE Document SET approval_status = %s WHERE doc_id = %s AND production_id = %s",
            (decision, doc_id, production_id),
        )
        return cur.rowcount
