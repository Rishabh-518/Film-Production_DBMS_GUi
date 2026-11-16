import psycopg2
import streamlit as st

import navigation
from auth import authenticate, user_classes
from productions import current_first, filter_productions, productions_visible_to
from ui_common import show_flash
from ui_home import show_home, show_production_overview
from access import can
from ui_records import show_my_contact, show_new_production

FILTER_KEYS = ("search", "status_filter", "type_filter", "show_all")


def show_login():
    st.title("Film and Theatre Production Database")

    with st.form("login"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")

    if not submitted:
        return
    if not email or not password:
        st.error("Enter both email and password.")
        return

    account = authenticate(email, password)
    if account is None:
        st.error("Incorrect email or password.")
        return

    st.session_state.account = account
    st.rerun()


def go_to(page):
    st.session_state.page = page


def leave_production():
    st.session_state.pop("production_id", None)
    st.session_state.page = navigation.HOME


def show_sidebar(account, production, classes, productions):
    with st.sidebar:
        st.subheader(account["full_name"] or "Administrator")
        st.caption(account["email"])
        st.write(f"**Access:** {', '.join(sorted(classes))}")

        if production is not None:
            st.divider()
            st.write(f"**{production['title']}**")
            st.caption(f"{production['status']} | {', '.join(production['roles']) or 'all productions'}")
            st.button("Switch production", on_click=leave_production, icon=":material/swap_horiz:",
                      key="switch_production", width="stretch")

        current = st.session_state.page
        for group, pages in navigation.sections(classes, production is not None):
            st.caption(group.upper())
            for name in pages:
                is_current = name == current
                st.button(
                    name,
                    key=f"nav_{name}",
                    on_click=leave_production if name == navigation.HOME else go_to,
                    args=None if name == navigation.HOME else (name,),
                    type="primary" if is_current else "secondary",
                    width="stretch",
                )

        st.divider()
        if st.button("Log out", key="log_out", icon=":material/logout:", width="stretch"):
            st.session_state.clear()
            st.rerun()


def choice_filter(label, key, productions, column):
    values = sorted({p[column] for p in productions if p[column]})
    return st.selectbox(label, ["All", *values], key=key)


def show_filters(productions):
    search_column, status_column, type_column, all_column = st.columns([3, 2, 2, 2])
    with search_column:
        search = st.text_input("Search by title", key="search", icon=":material/search:")
    with status_column:
        status = choice_filter("Status", "status_filter", productions, "status")
    with type_column:
        production_type = choice_filter("Type", "type_filter", productions, "production_type")
    with all_column:
        show_all = st.toggle("Show all (include completed and archived)", key="show_all")
    matching = filter_productions(productions, search, status, production_type)
    return current_first(matching, show_all), show_all


def show_picker(account, productions, classes):
    st.subheader("Productions")
    if navigation.allowed(classes, "manage_production"):
        show_new_production(classes, account["person_id"])

    if not productions:
        st.info("You are not assigned to any production yet.")
        return

    matching, show_all = show_filters(productions)
    if not matching:
        st.info("No productions match. Turn on Show all, or change the search and filters.")
        return

    st.caption(
        f"Showing {len(matching)} of {len(productions)}"
        f"{'' if show_all else ' (active productions only)'}. Click a row to open it."
    )
    rows = [
        {
            "Title": p["title"],
            "Type": p["production_type"],
            "Status": p["status"],
            "Start": p["start_date"],
            "End": p["end_date"],
            **({} if account["is_admin"] or account["account_class"] else {"Your roles": ", ".join(p["roles"])}),
        }
        for p in matching
    ]
    table = st.dataframe(
        rows,
        hide_index=True,
        height=500,
        key="production_table",
        on_select="rerun",
        # With cell selection alone, clicking a header also selects the first row
        # and would open it. Allowing column selection keeps header clicks harmless.
        selection_mode=["single-cell", "single-column"],
        alt="Productions you can open",
    )
    if table.selection.cells:
        row_index, _ = table.selection.cells[0]
        st.session_state.production_id = matching[row_index]["production_id"]
        st.session_state.page = navigation.OVERVIEW
        st.rerun()


def show_home_page(account, productions, classes):
    st.title("Home")
    show_flash()
    names = ["Needs attention", "Productions"]
    own_contact = can(classes, "update_own_contact") and account["person_id"] is not None
    if own_contact:
        names.append("My details")
    tabs = st.tabs(names)
    with tabs[0]:
        classes_of = lambda p: user_classes(account, p["roles"])  # noqa: E731
        show_home(account, productions, classes_of)
    with tabs[1]:
        show_picker(account, productions, classes)
    if own_contact:
        with tabs[2]:
            show_my_contact(account, classes)


def show_page(page, production, account, classes, productions):
    if page == navigation.HOME:
        show_home_page(account, productions, classes)
        return
    show_flash()
    if page == navigation.OVERVIEW:
        show_production_overview(production, account, classes)
    else:
        navigation.render(page, production, account, classes)


def main():
    account = st.session_state.get("account")
    if account is None:
        show_login()
        return

    # Streamlit forgets a widget's value on any run that does not draw it. This
    # keeps the search and filters while a production is open.
    for key in FILTER_KEYS:
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]

    # Reloaded on every run, so removing someone from a production takes effect at once.
    productions = productions_visible_to(account)
    selected_id = st.session_state.get("production_id")
    production = next(
        (p for p in productions if p["production_id"] == selected_id), None
    )

    # Outside a production the classes are everything the user holds anywhere.
    if production:
        classes = user_classes(account, production["roles"])
    else:
        classes = user_classes(account, [r for p in productions for r in p["roles"]])

    pages = navigation.page_names(classes, production is not None)
    fallback = navigation.OVERVIEW if production else navigation.HOME
    if st.session_state.get("page") not in pages:
        st.session_state.page = fallback
    show_sidebar(account, production, classes, productions)
    show_page(st.session_state.page, production, account, classes, productions)


st.set_page_config(
    page_title="Production Database",
    layout="wide" if "account" in st.session_state else "centered",
)

try:
    main()
except psycopg2.OperationalError:
    st.error("Could not connect to the database. Check db_config.py.")
