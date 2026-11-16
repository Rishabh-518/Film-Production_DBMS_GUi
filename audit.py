"""Audit history: approval status of expenses and documents, and call-sheet revisions."""
from access import ADMIN, PRODUCER, RuleError, require
from db import transaction
from schedule import is_assigned


def audit_sections(production_id, classes, person_id=None):
    """Return [(title, rows)]. Admin sees everything, a Producer their own production,
    Finance the expenses only. production_id None means all productions (Admin only)."""
    require(classes, "view_audit")
    if production_id is None and ADMIN not in classes:
        raise RuleError("Choose a production to see its audit history.")
    with transaction() as cur:
        if PRODUCER in classes and ADMIN not in classes and not is_assigned(cur, production_id, person_id):
            raise RuleError("You can only see the audit history of your own production.")
        sections = [("Expense approvals", expense_history(cur, production_id))]
        if set(classes) & {ADMIN, PRODUCER}:
            sections.append(("Document approvals", document_history(cur, production_id)))
            sections.append(("Call sheet revisions", call_sheet_history(cur, production_id)))
        return sections


def expense_history(cur, production_id):
    cur.execute(
        """
        SELECT p.title AS production, e.expense_id, d.department_name, bl.category, e.vendor,
               e.expense_date, e.amount, e.approval_status
        FROM Expense e
        JOIN BudgetLine bl ON bl.line_id = e.line_id
        JOIN Budget b ON b.budget_id = bl.budget_id
        JOIN Production p ON p.production_id = b.production_id
        LEFT JOIN Department d ON d.department_id = bl.department_id
        WHERE %s::INT IS NULL OR b.production_id = %s::INT
        ORDER BY p.title, e.expense_date DESC, e.expense_id DESC
        """,
        (production_id, production_id),
    )
    return cur.fetchall()


def document_history(cur, production_id):
    cur.execute(
        """
        SELECT p.title AS production, doc.doc_id, doc.title, doc.doc_type, doc.version_no,
               doc.approval_status
        FROM Document doc JOIN Production p ON p.production_id = doc.production_id
        WHERE %s::INT IS NULL OR doc.production_id = %s::INT
        ORDER BY p.title, doc.title, doc.version_no
        """,
        (production_id, production_id),
    )
    return cur.fetchall()


def call_sheet_history(cur, production_id):
    cur.execute(
        """
        SELECT p.title AS production, cs.sheet_id, e.event_id, e.event_type, cs.call_date,
               cs.revision_no, cs.status
        FROM CallSheet cs
        JOIN ProductionEvent e ON e.event_id = cs.event_id
        JOIN Production p ON p.production_id = e.production_id
        WHERE %s::INT IS NULL OR e.production_id = %s::INT
        ORDER BY p.title, e.event_id, cs.revision_no
        """,
        (production_id, production_id),
    )
    return cur.fetchall()
