import streamlit as st

import budget
import team
from access import can
from ui_common import attempt, lookup, pick, show_table

WARNING_TEXT = {
    "over": "Overspent: spending is above the planned amount.",
    "near": "Warning: spending has reached 90% or more of the planned amount.",
}

SHORT_WARNING = {"over": "Overspent", "near": "90% or more used"}


def show_warning(warning):
    if warning:
        st.warning(WARNING_TEXT[warning])


def expense_message(result):
    expense_id, warning = result
    message = f"Expense {expense_id} submitted as Pending."
    return f"{message} {WARNING_TEXT[warning]}" if warning else message


def decision_message(text):
    return lambda warning: f"{text} {WARNING_TEXT[warning]}" if warning else text


def show_budget(production, classes, account=None):
    st.title("Budget")
    account = account or st.session_state.get("account")
    production_id = production["production_id"]
    budgets = budget.list_budgets(production_id)
    if not can(classes, "view_budget_lines"):
        st.caption("You can submit an expense request. Budget figures are not shown to your access level.")
        show_expense_form(budgets, classes, account)
        return
    departments = budget.department_filter(production_id, classes, account["person_id"])
    if departments is not None:
        st.caption("Showing the budget lines of your own department only.")
    lines_tab, expenses_tab = st.tabs(["Budget lines", "Expenses"])
    with lines_tab:
        if can(classes, "manage_budget") and st.button("Create new version", key="new_version"):
            attempt(budget.create_budget_version, production_id, classes,
                    done="New draft budget created (id {result})")
        current = pick("Budget version", budgets, "budget_pick",
                       lambda b: f"Version {b['version_no']} ({b['status']})")
        if current is not None:
            show_lines(current, classes, production_id, departments)
    with expenses_tab:
        show_expenses(production_id, budgets, classes, account, departments)


def show_lines(current, classes, production_id, departments):
    lines = budget.list_lines(current["budget_id"], departments)
    total = budget.totals(lines)
    for column, name in zip(st.columns(4), ["planned", "committed", "actual", "difference"]):
        column.metric(name.capitalize(), f"{total[name]:,.2f}")
    show_warning(total["warning"])
    shown = [{**line, "warning": SHORT_WARNING.get(line["warning"], "")} for line in lines]
    show_table(shown, "budget_lines", "budget_lines",
               {"warning": st.column_config.TextColumn("Warning", width="medium")})
    for line in lines:
        if line["warning"]:
            st.warning(f"{line['department_name']} / {line['category']}: {WARNING_TEXT[line['warning']]}")

    locked = current["status"] in ("Approved", "Superseded")
    if locked:
        st.info(f"This budget is {current['status']}, so its lines are read-only.")
    if not can(classes, "manage_budget") or locked:
        return
    add_tab, edit_tab = st.tabs(["Add line", "Edit or delete line"])
    with add_tab:
        departments = team.list_departments(production_id)
        names, ids = lookup(departments, "department_id", "department_name", include_none=True)
        with st.form("add_line", clear_on_submit=True):
            department_id = st.selectbox("Department", ids, format_func=lambda d: names.get(d, "(none)"))
            category = st.text_input("Category")
            planned = st.number_input("Planned amount", min_value=0.0, step=100.0)
            committed = st.number_input("Committed amount", min_value=0.0, step=100.0)
            if st.form_submit_button("Add line"):
                attempt(budget.add_line, current["budget_id"], department_id, category,
                        planned, committed, classes, done="Line added (rows affected: {result})")
    with edit_tab:
        line = pick("Line", lines, "line_pick",
                    lambda row: f"{row['department_name'] or '(none)'} / {row['category']}")
        if line is not None:
            with st.form("edit_line"):
                planned = st.number_input("Planned", min_value=0.0, value=float(line["planned"]))
                committed = st.number_input("Committed", min_value=0.0, value=float(line["committed"]))
                save, delete = st.columns(2)
                if save.form_submit_button("Save line"):
                    attempt(budget.update_line, line["line_id"], planned, committed, classes,
                            done="Line updated (rows affected: {result})")
                if delete.form_submit_button("Delete line"):
                    attempt(budget.delete_line, line["line_id"], classes,
                            done="Line deleted (rows affected: {result})")
    if can(classes, "manage_budget") and st.button(
            "Approve this budget (makes it read-only)", key="approve_budget"):
        attempt(budget.approve_budget, current["budget_id"], classes,
                done="Budget approved (rows affected: {result})")


def show_expenses(production_id, budgets, classes, account, departments):
    status = st.selectbox("Status", ["All", "Pending", "Approved", "Rejected"], key="expense_filter")
    expenses = budget.list_expenses(production_id, status, departments)
    show_table(expenses, "expenses", "expenses")
    show_expense_form(budgets, classes, account)

    if can(classes, "approve_expense"):
        pending = [e for e in budget.list_expenses(production_id, "Pending")]
        expense = pick("Pending expense", pending, "decide_pick",
                       lambda e: f"#{e['expense_id']} {e['vendor']} {e['amount']}")
        if expense is not None:
            approve, reject = st.columns(2)
            if approve.button("Approve", key="approve_expense"):
                attempt(budget.decide_expense, expense["expense_id"], "Approved", classes,
                        done=decision_message("Expense approved."))
            if reject.button("Reject", key="reject_expense"):
                attempt(budget.decide_expense, expense["expense_id"], "Rejected", classes,
                        done=decision_message("Expense rejected."))


def show_expense_form(budgets, classes, account):
    if not can(classes, "request_expense") or not budgets:
        return
    usable = [b for b in budgets if b["status"] in ("Approved", "Draft", "Pending")]
    chosen = pick("Budget for the new expense", usable, "expense_budget",
                  lambda b: f"Version {b['version_no']} ({b['status']})")
    lines = budget.list_lines(chosen["budget_id"]) if chosen else []
    with st.form("add_expense", clear_on_submit=True):
        line = pick("Budget line", lines, "expense_line",
                    lambda row: f"{row['department_name'] or '(none)'} / {row['category']}")
        vendor = st.text_input("Vendor")
        when = st.date_input("Date")
        amount = st.number_input("Amount", min_value=0.0, step=10.0)
        receipt = st.text_input("Receipt link")
        if st.form_submit_button("Submit expense") and line is not None:
            attempt(budget.add_expense, line["line_id"], vendor, when, amount, receipt,
                    classes, account["person_id"], done=expense_message)
