"""Who may do what (SRS section 9) and the rules every write function shares."""

ADMIN = "Admin"
PRODUCER = "Producer"
STAGE = "Stage Management"
DEPT_HEAD = "Department Head"
RESOURCE = "Resource Coordinator"
FINANCE = "Finance"
CAST_CREW = "Cast / Crew"
VIEWER = "Viewer"

EVERYONE = {ADMIN, PRODUCER, STAGE, DEPT_HEAD, RESOURCE, FINANCE, CAST_CREW, VIEWER}

# Each action lists the user classes allowed to do it. A user may hold several
# classes, and one of them is enough. Read it next to the SRS section 9 matrix.
# Where the matrix says "own dept", "proposed" or "request", the action is
# allowed here and the write function narrows it further.
ACTIONS = {
    # Accounts and roles: Admin only
    "view_accounts": {ADMIN},
    "manage_accounts": {ADMIN},
    # Production details: Admin and Producer M, everyone else V
    "view_overview": EVERYONE,
    "manage_production": {ADMIN, PRODUCER},
    # People and assignments: Admin, Producer, Stage M; Dept Head M own dept; Cast S own
    "view_team": EVERYONE - {VIEWER},
    # Records page (production, venues, people): only the classes that edit them
    "view_records": {ADMIN, PRODUCER, STAGE, RESOURCE},
    "manage_people": {ADMIN, PRODUCER, STAGE},
    "manage_assignments": {ADMIN, PRODUCER, STAGE, DEPT_HEAD},
    "manage_tasks": {ADMIN, PRODUCER, STAGE, DEPT_HEAD},
    "manage_departments": {ADMIN, PRODUCER},
    "update_own_contact": {CAST_CREW},
    # Schedule and events: Admin, Producer, Stage M; Dept Head M proposed; Cast V own
    "view_schedule": EVERYONE,
    "manage_schedule": {ADMIN, PRODUCER, STAGE},
    "propose_event": {DEPT_HEAD},
    "approve_event": {ADMIN, PRODUCER, STAGE},
    # Call sheets: Producer, Stage M; Admin, Dept, Resource V; Cast acknowledges; Finance X
    "view_call_sheets": EVERYONE - {FINANCE},
    "manage_call_sheets": {PRODUCER, STAGE},
    "acknowledge_call_sheet": {PRODUCER, STAGE, DEPT_HEAD, RESOURCE, CAST_CREW},
    # Resources and venues: Admin, Resource M; Dept and Cast request
    "view_resources": EVERYONE - {VIEWER},
    "view_issue_return": {ADMIN, PRODUCER, STAGE, RESOURCE, FINANCE},
    "manage_resources": {ADMIN, RESOURCE},
    "reserve_resource": {ADMIN, PRODUCER, STAGE, RESOURCE},
    "request_resource": {DEPT_HEAD, CAST_CREW},
    "manage_venues": {ADMIN, RESOURCE},
    # Budgets and expenses: Producer, Finance M/A; Dept views own dept; Resource and Cast request
    "view_budget": {ADMIN, PRODUCER, DEPT_HEAD, RESOURCE, FINANCE, CAST_CREW},
    "view_budget_lines": {ADMIN, PRODUCER, DEPT_HEAD, RESOURCE, FINANCE},
    "manage_budget": {PRODUCER, FINANCE},
    "request_expense": {PRODUCER, FINANCE, RESOURCE, CAST_CREW},
    "approve_expense": {PRODUCER, FINANCE},
    # Documents: Admin, Producer, Stage, Dept M; the rest V
    "view_documents": EVERYONE,
    "manage_documents": {ADMIN, PRODUCER, STAGE, DEPT_HEAD},
    "approve_document": {ADMIN, PRODUCER},
    # Reports: everyone V (reports.py narrows what each class sees)
    # Audit history: Admin V, Producer V own production, Finance V finance only
    "view_audit": {ADMIN, PRODUCER, FINANCE},
}

# Sidebar entry -> the action that lets a user see it.
MODULES = {
    "Overview": "view_overview",
    "Schedule": "view_schedule",
    "Call sheets": "view_call_sheets",
    "Resources": "view_resources",
    "Issue and return": "view_issue_return",
    "Budget": "view_budget",
    "Team and tasks": "view_team",
    "Documents": "view_documents",
    "Records": "view_records",
    "Accounts": "view_accounts",
    "Audit history": "view_audit",
}


class RuleError(Exception):
    """A business rule stopped the change. The message is safe to show the user."""


class PermissionDenied(RuleError):
    pass


class ClashError(RuleError):
    """Raised when a booking overlaps another one and was not confirmed."""

    def __init__(self, clashes):
        super().__init__(f"{len(clashes)} clash(es) found. Review them and confirm to save.")
        self.clashes = clashes


def can(classes, action):
    return bool(set(classes) & ACTIONS[action])


def require(classes, action):
    if not can(classes, action):
        raise PermissionDenied(f"Your access level does not allow this ({action.replace('_', ' ')}).")


def visible_modules(classes):
    return [name for name, action in MODULES.items() if can(classes, action)]


def check_production_open(cur, production_id):
    """Archived productions keep their history, so no write may touch them."""
    cur.execute(
        "SELECT status FROM Production WHERE production_id = %s", (production_id,)
    )
    row = cur.fetchone()
    if row is None:
        raise RuleError("That production does not exist.")
    if row["status"] == "Archived":
        raise RuleError("This production is archived, so its records are read-only.")


def sees_all_departments(classes):
    """Only a Department Head acting alone is limited to their own departments."""
    return bool(set(classes) & {ADMIN, PRODUCER, STAGE, FINANCE, RESOURCE})
