"""Which pages exist, how they are grouped, and which screen function draws each."""
import streamlit as st

from access import ACTIONS, can

HOME = "Home"
OVERVIEW = "Overview"

# Group -> [(page, action that lets a user see it, needs an open production)].
GROUPS = {
    "Home": [(HOME, "view_overview", False)],
    "Production": [
        (OVERVIEW, "view_overview", True),
        ("Schedule", "view_schedule", True),
        ("Call sheets", "view_call_sheets", True),
        ("People and tasks", "view_team", True),
        ("Documents", "view_documents", True),
        ("Records", "view_records", True),
    ],
    "Resources": [
        ("Catalogue", "view_resources", False),
        ("Issue and return", "view_issue_return", False),
    ],
    "Money": [
        ("Budget and expenses", "view_budget", True),
        ("Audit history", "view_audit", False),
    ],
    "Admin": [("Accounts", "view_accounts", False)],
}


def allowed(classes, action):
    # Accounts and audit actions may not be defined yet; hide those pages until they are.
    return action in ACTIONS and can(classes, action)


def sections(classes, in_production):
    """[(group, [pages])] for this user. Groups with no visible page are left out."""
    result = []
    for group, pages in GROUPS.items():
        names = [
            name
            for name, action, needs_production in pages
            if allowed(classes, action) and (in_production or not needs_production)
        ]
        if names:
            result.append((group, names))
    return result


def page_names(classes, in_production):
    return [name for _, names in sections(classes, in_production) for name in names]


def page_action(page):
    for pages in GROUPS.values():
        for name, action, _ in pages:
            if name == page:
                return action
    return None


def show_unavailable(page):
    st.title(page)
    st.info(f"{page} is not available yet.")


def show_accounts_page(account, classes):
    try:
        from ui_accounts import show_accounts
    except ImportError:
        show_unavailable("Accounts")
        return
    show_accounts(account, classes)


def show_audit_page(production, account, classes):
    try:
        from ui_audit import show_audit
    except ImportError:
        show_unavailable("Audit history")
        return
    show_audit(production, account, classes)


def render(page, production, account, classes):
    """Draw one page. Imports are local so a missing screen cannot stop the app."""
    from ui_budget import show_budget
    from ui_callsheets import show_call_sheets
    from ui_records import show_records
    from ui_resources import show_issue_and_return, show_resources
    from ui_schedule import show_schedule
    from ui_team import show_documents, show_team

    if page == "Catalogue":
        show_resources(classes, production, account)
    elif page == "Issue and return":
        show_issue_and_return(classes)
    elif page == "Accounts":
        show_accounts_page(account, classes)
    elif page == "Schedule":
        show_schedule(production, account, classes)
    elif page == "Call sheets":
        show_call_sheets(production, account, classes)
    elif page == "People and tasks":
        show_team(production, account, classes)
    elif page == "Documents":
        show_documents(production, classes)
    elif page == "Budget and expenses":
        show_budget(production, classes, account)
    elif page == "Records":
        show_records(production, classes)
    elif page == "Audit history":
        show_audit_page(production, account, classes)
