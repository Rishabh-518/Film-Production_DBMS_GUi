import streamlit as st

import accounts
from ui_common import attempt, pick, show_table


def show_accounts(account, classes):
    st.title("Accounts and roles")
    rows = accounts.list_accounts(classes)
    show_table(rows, "accounts", "accounts")
    create_tab, change_tab = st.tabs(["Create account", "Change an account"])
    with create_tab:
        show_create_form(classes)
    with change_tab:
        show_change_forms(rows, account, classes)


def show_create_form(classes):
    people = accounts.people_without_account(classes)
    with st.form("create_account", clear_on_submit=True):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        is_admin = st.checkbox("Administrator account (no linked person)")
        person = st.selectbox(
            "Linked person", [None, *people],
            format_func=lambda p: "(none)" if p is None else f"{p['full_name']} (#{p['person_id']})",
        )
        account_class = st.selectbox(
            "Access class", accounts.ACCOUNT_CLASSES,
            format_func=lambda c: c or "(from role assignments)",
        )
        if st.form_submit_button("Create account"):
            attempt(accounts.create_account, email, password,
                    person["person_id"] if person else None, is_admin, account_class, classes,
                    done="Account {result} created")


def show_change_forms(rows, account, classes):
    chosen = pick("Account", rows, "account_pick",
                  lambda a: f"{a['email']} ({'active' if a['is_active'] else 'disabled'})")
    if chosen is None:
        return
    account_id = chosen["account_id"]
    toggle = "Disable" if chosen["is_active"] else "Enable"
    if st.button(f"{toggle} this account", key="toggle_account"):
        attempt(accounts.set_active, account_id, not chosen["is_active"], classes,
                account["account_id"], done="Account updated (rows affected: {result})")
    with st.form("account_class_form"):
        account_class = st.selectbox(
            "Access class", accounts.ACCOUNT_CLASSES,
            index=accounts.ACCOUNT_CLASSES.index(chosen["account_class"]),
            format_func=lambda c: c or "(from role assignments)",
        )
        if st.form_submit_button("Save access class"):
            attempt(accounts.set_account_class, account_id, account_class, classes,
                    done="Access class saved (rows affected: {result})")
    with st.form("reset_password_form", clear_on_submit=True):
        new_password = st.text_input("New password", type="password")
        if st.form_submit_button("Reset password"):
            attempt(accounts.reset_password, account_id, new_password, classes,
                    done="Password reset (rows affected: {result})")
