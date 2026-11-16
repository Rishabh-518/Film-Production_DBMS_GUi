"""Home page and production overview: what needs attention, with links to where to act."""
import streamlit as st

import reports
from access import ADMIN, CAST_CREW, DEPT_HEAD, FINANCE, PRODUCER, RESOURCE, STAGE, VIEWER
from navigation import allowed, page_action
from productions import is_current, production_summary

OVERSIGHT = {ADMIN, RESOURCE, VIEWER}
MANAGERS = {ADMIN, PRODUCER, STAGE}

# Lists that are not about one production, so the production overview leaves them out.
HOME_ONLY = ("status", "returns", "damaged")

# (key, title, classes that see it, query(ids, person_id), page that fixes it, text when empty)
SECTIONS = [
    ("status", "Active productions by status", OVERSIGHT,
     lambda ids, person: reports.status_counts(ids), None, "No productions."),
    ("week", "Events in the next 7 days", {ADMIN, PRODUCER, STAGE, RESOURCE, VIEWER, FINANCE},
     lambda ids, person: reports.events_this_week(ids), "Schedule",
     "No events in the next 7 days."),
    ("clashes", "Booking clashes", {ADMIN, PRODUCER, STAGE, RESOURCE},
     lambda ids, person: reports.event_clashes(ids), "Schedule", "No booking clashes."),
    ("sheets", "Call sheets not yet acknowledged (next 7 days)",
     {ADMIN, PRODUCER, STAGE, VIEWER},
     lambda ids, person: reports.unacknowledged_sheets(ids), "Call sheets",
     "Every issued call sheet for the next 7 days is acknowledged."),
    ("expenses", "Pending expenses", {ADMIN, PRODUCER, FINANCE, RESOURCE, DEPT_HEAD},
     lambda ids, person: reports.pending_expenses(ids), "Budget and expenses",
     "No expenses waiting for approval."),
    ("budget", "Budget lines at 90% or more of plan", {ADMIN, PRODUCER, FINANCE, RESOURCE, VIEWER},
     lambda ids, person: reports.budget_alerts(ids), "Budget and expenses",
     "No budget line is close to its plan."),
    ("documents", "Documents waiting for approval", {ADMIN, PRODUCER, VIEWER},
     lambda ids, person: reports.pending_documents(ids), "Documents",
     "No documents waiting for approval."),
    ("overdue_tasks", "Overdue tasks", {ADMIN, PRODUCER, STAGE},
     lambda ids, person: reports.overdue_tasks_in(ids), "People and tasks", "No overdue tasks."),
    ("dept_tasks", "Open tasks in your department", {DEPT_HEAD},
     lambda ids, person: reports.department_tasks(person, ids), "People and tasks",
     "No open tasks in your department."),
    ("returns", "Overdue returns", {ADMIN, RESOURCE, VIEWER, STAGE},
     lambda ids, person: _overdue_returns(), "Issue and return", "No overdue returns."),
    ("damaged", "Items Damaged or Under Repair", {ADMIN, RESOURCE, VIEWER},
     lambda ids, person: reports.damaged_resources(), "Catalogue",
     "No items are damaged or under repair."),
    ("my_calls", "My next calls", {CAST_CREW},
     lambda ids, person: reports.next_calls(person, ids), "Schedule", "You have no upcoming calls."),
    ("my_sheets", "Call sheets to acknowledge", {CAST_CREW},
     lambda ids, person: reports.sheets_to_acknowledge(person, ids), "Call sheets",
     "No call sheets are waiting for you."),
    ("my_tasks", "My open tasks", {CAST_CREW},
     lambda ids, person: reports.open_tasks_of(person, ids), "People and tasks",
     "You have no open tasks."),
]

TILE_NAMES = {
    "status": "Active productions",
    "week": "Events this week",
    "clashes": "Clashes",
    "sheets": "Sheets to chase",
    "expenses": "Pending expenses",
    "budget": "Budget alerts",
    "documents": "Pending documents",
    "overdue_tasks": "Overdue tasks",
    "dept_tasks": "Department tasks",
    "returns": "Overdue returns",
    "damaged": "Damaged or repair",
    "my_calls": "My next calls",
    "my_sheets": "To acknowledge",
    "my_tasks": "My open tasks",
}


def _overdue_returns():
    from movements import overdue_returns  # Q19

    return overdue_returns()


def scopes_for(account, productions, classes_of):
    """{user class: [production ids where they hold it]}. classes_of(p) gives the classes."""
    scopes = {}
    for production in productions:
        for user_class in classes_of(production):
            scopes.setdefault(user_class, []).append(production["production_id"])
    return scopes


def ids_for(scopes, wanted):
    ids = {i for user_class in wanted & set(scopes) for i in scopes[user_class]}
    return sorted(ids)


def open_target(production_id, page):
    if production_id is not None:
        st.session_state.production_id = production_id
    if page is not None:
        st.session_state.page = page


def show_linked_table(rows, key, page, can_open):
    """A table whose row selection opens the page that fixes the problem."""
    shown = [{k: v for k, v in row.items() if k != "production_id"} for row in rows]
    linked = can_open and page is not None
    if not linked:
        st.dataframe(shown, hide_index=True, key=f"home_{key}")
        return
    table = st.dataframe(
        shown, hide_index=True, key=f"home_{key}", on_select="rerun", selection_mode="single-row"
    )
    caption = f"Select a row to open {page}."
    st.caption(caption)
    if table.selection.rows:
        row = rows[table.selection.rows[0]]
        open_target(row.get("production_id"), page)
        st.rerun()


def show_tiles(results):
    tiles = [(TILE_NAMES[key], _tile_value(key, rows)) for key, rows in results]
    for start in range(0, len(tiles), 5):
        chunk = tiles[start:start + 5]
        for column, (name, value) in zip(st.columns(5), chunk):
            column.metric(name, value)


def _tile_value(key, rows):
    if key == "status":
        return sum(r["productions"] for r in rows if r["status"] not in ("Archived", "Completed"))
    return len(rows)


def show_attention(account, scopes, key_prefix, skip=()):
    """Tiles first, then one table per section. Sections the user's classes do not see are skipped."""
    person = account["person_id"]
    results = []
    for key, title, wanted, query, page, empty in SECTIONS:
        if key in skip:
            continue
        ids = ids_for(scopes, wanted)
        if ids:
            results.append((key, query(ids, person)))
    if not results:
        st.info("Nothing to show for your access level yet.")
        return
    show_tiles(results)

    by_key = {s[0]: s for s in SECTIONS}
    for key, rows in results:
        _, title, _, _, page, empty = by_key[key]
        st.subheader(title)
        if not rows:
            st.caption(empty)
            continue
        can_open = page is None or allowed(set(scopes), page_action(page))
        show_linked_table(rows, f"{key_prefix}_{key}", page, can_open)


def show_home(account, productions, classes_of):
    st.subheader("Needs attention")
    st.caption("Select a row in any table to open the page where you can act on it.")
    live = [p for p in productions if is_current(p)] or productions
    scopes = scopes_for(account, live, classes_of)
    show_attention(account, scopes, "home")


def show_production_overview(production, account, classes):
    st.title(production["title"])
    st.caption(
        f"{production['production_type']} | {production['status']} | "
        f"{production['start_date']} to {production['end_date']}"
    )
    if production["status"] == "Archived":
        st.warning("This production is archived, so its records are read-only.")

    summary = production_summary(production["production_id"])
    for column, (name, value) in zip(st.columns(len(summary)), summary.items()):
        column.metric(name.replace("_", " ").capitalize(), value)

    st.header("Needs attention here")
    scopes = {user_class: [production["production_id"]] for user_class in classes}
    show_attention(account, scopes, "overview", skip=HOME_ONLY)
