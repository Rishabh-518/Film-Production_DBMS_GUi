"""Budget versions, lines and expenses. Planned, committed and actual stay separate."""
from decimal import Decimal

from access import PRODUCER, FINANCE, RESOURCE, RuleError, check_production_open, require, sees_all_departments
from db import transaction
from schedule import is_assigned
from team import own_department_ids

NEAR_LIMIT = Decimal("0.9")
BUDGET_STATUSES = ["Draft", "Pending", "Approved", "Superseded"]


def spend_warning(planned, spent):
    """Return 'over', 'near' or None for an amount spent against a planned amount."""
    if spent > planned:
        return "over"
    if planned > 0 and spent >= planned * NEAR_LIMIT:
        return "near"
    return None


def list_budgets(production_id):
    with transaction() as cur:
        cur.execute(
            "SELECT budget_id, version_no, effective_date, status FROM Budget "
            "WHERE production_id = %s ORDER BY version_no DESC",
            (production_id,),
        )
        return cur.fetchall()


def budget_context(cur, budget_id, for_lines=True):
    """Look up the budget's production and status, enforcing the read-only rules."""
    cur.execute(
        "SELECT production_id, status FROM Budget WHERE budget_id = %s FOR UPDATE", (budget_id,)
    )
    budget = cur.fetchone()
    if budget is None:
        raise RuleError("That budget does not exist.")
    check_production_open(cur, budget["production_id"])
    if for_lines and budget["status"] in ("Approved", "Superseded"):
        raise RuleError(f"A {budget['status']} budget is read-only. Create a new version to change it.")
    return budget


def create_budget_version(production_id, classes):
    """New Draft version that starts as a copy of the latest version's lines."""
    require(classes, "manage_budget")
    with transaction() as cur:
        check_production_open(cur, production_id)
        cur.execute(
            """
            INSERT INTO Budget (budget_id, production_id, version_no, effective_date, status)
            SELECT (SELECT COALESCE(MAX(budget_id), 0) + 1 FROM Budget), %s,
                   COALESCE(MAX(version_no), 0) + 1, CURRENT_DATE, 'Draft'
            FROM Budget WHERE production_id = %s
            RETURNING budget_id, version_no
            """,
            (production_id, production_id),
        )
        new = cur.fetchone()
        cur.execute(
            """
            INSERT INTO BudgetLine (line_id, budget_id, department_id, category,
                                    planned_amount, committed_amount)
            SELECT (SELECT COALESCE(MAX(line_id), 0) FROM BudgetLine) + ROW_NUMBER() OVER (ORDER BY bl.line_id),
                   %s, bl.department_id, bl.category, bl.planned_amount, bl.committed_amount
            FROM BudgetLine bl
            WHERE bl.budget_id = (SELECT budget_id FROM Budget
                                  WHERE production_id = %s AND budget_id <> %s
                                  ORDER BY version_no DESC LIMIT 1)
            """,
            (new["budget_id"], production_id, new["budget_id"]),
        )
        return new["budget_id"]


def approve_budget(budget_id, classes):
    """Approving locks the budget and supersedes the previously approved one."""
    require(classes, "manage_budget")
    with transaction() as cur:
        budget = budget_context(cur, budget_id)
        cur.execute(
            "UPDATE Budget SET status = 'Superseded' "
            "WHERE production_id = %s AND status = 'Approved'",
            (budget["production_id"],),
        )
        cur.execute("UPDATE Budget SET status = 'Approved' WHERE budget_id = %s", (budget_id,))
        return cur.rowcount


def department_filter(production_id, classes, person_id):
    """None means every department. A Department Head sees their own departments only."""
    if sees_all_departments(classes):
        return None
    with transaction() as cur:
        return own_department_ids(cur, production_id, person_id)


def list_lines(budget_id, department_ids=None):
    """One row per line with planned, committed, actual (approved) and pending amounts."""
    with transaction() as cur:
        cur.execute(
            """
            SELECT bl.line_id, d.department_name, bl.category, bl.department_id,
                   bl.planned_amount AS planned, bl.committed_amount AS committed,
                   COALESCE(SUM(e.amount) FILTER (WHERE e.approval_status = 'Approved'), 0) AS actual,
                   COALESCE(SUM(e.amount) FILTER (WHERE e.approval_status = 'Pending'), 0) AS pending
            FROM BudgetLine bl
            LEFT JOIN Department d ON d.department_id = bl.department_id
            LEFT JOIN Expense e ON e.line_id = bl.line_id
            WHERE bl.budget_id = %s
              AND (%s::INT[] IS NULL OR bl.department_id = ANY(%s::INT[]))
            GROUP BY bl.line_id, d.department_name
            ORDER BY d.department_name, bl.category
            """,
            (budget_id, department_ids, department_ids),
        )
        lines = cur.fetchall()
    for line in lines:
        line["difference"] = line["planned"] - line["actual"]
        line["warning"] = spend_warning(line["planned"], line["actual"] + line["pending"])
    return lines


def totals(lines):
    planned = sum(line["planned"] for line in lines)
    spent = sum(line["actual"] + line["pending"] for line in lines)
    return {
        "planned": planned,
        "committed": sum(line["committed"] for line in lines),
        "actual": sum(line["actual"] for line in lines),
        "difference": planned - sum(line["actual"] for line in lines),
        "warning": spend_warning(planned, spent),
    }


def add_line(budget_id, department_id, category, planned, committed, classes):
    require(classes, "manage_budget")
    with transaction() as cur:
        budget_context(cur, budget_id)
        cur.execute(
            """
            INSERT INTO BudgetLine (line_id, budget_id, department_id, category,
                                    planned_amount, committed_amount)
            SELECT COALESCE(MAX(line_id), 0) + 1, %s, %s, %s, %s, %s FROM BudgetLine
            """,
            (budget_id, department_id, category.strip(), planned, committed),
        )
        return cur.rowcount


def update_line(line_id, planned, committed, classes):
    require(classes, "manage_budget")
    with transaction() as cur:
        cur.execute("SELECT budget_id FROM BudgetLine WHERE line_id = %s", (line_id,))
        line = cur.fetchone()
        if line is None:
            raise RuleError("That budget line does not exist.")
        budget_context(cur, line["budget_id"])
        cur.execute(
            "UPDATE BudgetLine SET planned_amount = %s, committed_amount = %s WHERE line_id = %s",
            (planned, committed, line_id),
        )
        return cur.rowcount


def delete_line(line_id, classes):
    require(classes, "manage_budget")
    with transaction() as cur:
        cur.execute("SELECT budget_id FROM BudgetLine WHERE line_id = %s", (line_id,))
        line = cur.fetchone()
        if line is None:
            raise RuleError("That budget line does not exist.")
        budget_context(cur, line["budget_id"])
        cur.execute("SELECT COUNT(*) AS n FROM Expense WHERE line_id = %s", (line_id,))
        if cur.fetchone()["n"]:
            raise RuleError("This line has expenses, so it can't be deleted.")
        cur.execute("DELETE FROM BudgetLine WHERE line_id = %s", (line_id,))
        return cur.rowcount


def line_spend(cur, line_id):
    cur.execute(
        """
        SELECT bl.planned_amount,
               COALESCE(SUM(e.amount) FILTER (WHERE e.approval_status <> 'Rejected'), 0) AS spent
        FROM BudgetLine bl LEFT JOIN Expense e ON e.line_id = bl.line_id
        WHERE bl.line_id = %s GROUP BY bl.line_id
        """,
        (line_id,),
    )
    return cur.fetchone()


def add_expense(line_id, vendor, expense_date, amount, receipt_link, classes, person_id=None):
    """Record a Pending expense. Returns (expense_id, warning) where warning may be None.

    Cast / Crew may only request against a production they are assigned to.
    """
    require(classes, "request_expense")
    amount = Decimal(str(amount))  # the form gives a float; money is Decimal everywhere else
    with transaction() as cur:
        cur.execute(
            "SELECT b.production_id FROM BudgetLine bl JOIN Budget b ON b.budget_id = bl.budget_id "
            "WHERE bl.line_id = %s",
            (line_id,),
        )
        line = cur.fetchone()
        if line is None:
            raise RuleError("That budget line does not exist.")
        check_production_open(cur, line["production_id"])
        if not set(classes) & {PRODUCER, FINANCE, RESOURCE} and not is_assigned(
                cur, line["production_id"], person_id):
            raise RuleError("You can only request expenses for a production you are assigned to.")
        before = line_spend(cur, line_id)
        cur.execute(
            """
            INSERT INTO Expense (expense_id, line_id, vendor, expense_date, amount,
                                 approval_status, receipt_link)
            SELECT COALESCE(MAX(expense_id), 0) + 1, %s, %s, %s, %s, 'Pending', %s FROM Expense
            RETURNING expense_id
            """,
            (line_id, vendor.strip(), expense_date, amount, receipt_link.strip()),
        )
        expense_id = cur.fetchone()["expense_id"]
        return expense_id, spend_warning(before["planned_amount"], before["spent"] + amount)


def decide_expense(expense_id, decision, classes):
    """Only Finance and Producer approve or reject, and only Pending expenses."""
    require(classes, "approve_expense")
    if decision not in ("Approved", "Rejected"):
        raise RuleError("The decision must be Approved or Rejected.")
    with transaction() as cur:
        cur.execute(
            """
            SELECT e.approval_status, e.line_id, b.production_id
            FROM Expense e JOIN BudgetLine bl ON bl.line_id = e.line_id
            JOIN Budget b ON b.budget_id = bl.budget_id
            WHERE e.expense_id = %s FOR UPDATE OF e
            """,
            (expense_id,),
        )
        expense = cur.fetchone()
        if expense is None:
            raise RuleError("That expense does not exist.")
        check_production_open(cur, expense["production_id"])
        if expense["approval_status"] != "Pending":
            raise RuleError(f"This expense is already {expense['approval_status']}.")
        cur.execute(
            "UPDATE Expense SET approval_status = %s WHERE expense_id = %s",
            (decision, expense_id),
        )
        after = line_spend(cur, expense["line_id"])
        return spend_warning(after["planned_amount"], after["spent"])


def list_expenses(production_id, status="All", department_ids=None):
    with transaction() as cur:
        cur.execute(
            """
            SELECT e.expense_id, d.department_name, bl.category, e.vendor, e.expense_date,
                   e.amount, e.approval_status
            FROM Expense e
            JOIN BudgetLine bl ON bl.line_id = e.line_id
            JOIN Budget b ON b.budget_id = bl.budget_id
            LEFT JOIN Department d ON d.department_id = bl.department_id
            WHERE b.production_id = %s AND (%s = 'All' OR e.approval_status = %s)
              AND (%s::INT[] IS NULL OR bl.department_id = ANY(%s::INT[]))
            ORDER BY e.expense_date DESC, e.expense_id DESC
            """,
            (production_id, status, status, department_ids, department_ids),
        )
        return cur.fetchall()
