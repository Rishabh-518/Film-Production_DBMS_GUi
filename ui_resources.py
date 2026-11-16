from datetime import datetime, timedelta

import streamlit as st

import movements
import resources
import schedule
from access import can
from records import list_people
from ui_common import attempt, lookup, pick, show_table


def show_resources(classes, production=None, account=None):
    st.title("Resources")
    search_column, type_column, status_column, condition_column = st.columns(4)
    search = search_column.text_input("Search by name", key="res_search")
    resource_type = type_column.selectbox(
        "Type", ["All", *resources.resource_types()], key="res_type"
    )
    status = status_column.selectbox("Status", ["All", *resources.STATUSES], key="res_status")
    condition = condition_column.selectbox(
        "Condition", ["All", *resources.CONDITIONS], key="res_condition"
    )
    rows = resources.list_resources(search, resource_type, status, condition)
    st.caption(f"{len(rows)} resource(s)")
    show_table(rows, "resources", "resources")

    production_id = production["production_id"] if production else st.session_state.get("production_id")
    account = account or st.session_state.get("account")
    if production_id is not None and (can(classes, "request_resource") or can(classes, "manage_resources")):
        show_requests(production_id, account, classes, rows)

    if not can(classes, "manage_resources"):
        return
    add_tab, edit_tab = st.tabs(["Add resource", "Edit or delete"])
    with add_tab:
        with st.form("add_resource", clear_on_submit=True):
            name = st.text_input("Name")
            new_type = st.text_input("Type (for example Light, Camera)")
            new_condition = st.selectbox("Condition", resources.CONDITIONS)
            new_status = st.selectbox("Status", resources.STATUSES)
            if st.form_submit_button("Add"):
                attempt(resources.add_resource, name, new_type, new_condition, new_status, classes,
                        done="Resource added (rows affected: {result})")
    with edit_tab:
        item = pick("Resource", rows, "res_pick",
                    lambda r: f"{r['resource_name']} ({r['resource_type']}, {r['status']})")
        if item is None:
            return
        with st.form("edit_resource"):
            name = st.text_input("Name", item["resource_name"])
            new_type = st.text_input("Type", item["resource_type"] or "")
            new_condition = st.selectbox(
                "Condition", resources.CONDITIONS,
                index=resources.CONDITIONS.index(item["resource_condition"]),
            )
            new_status = st.selectbox(
                "Status", resources.STATUSES, index=resources.STATUSES.index(item["status"])
            )
            save, delete = st.columns(2)
            if save.form_submit_button("Save changes"):
                attempt(resources.update_resource, item["resource_id"], name, new_type,
                        new_condition, new_status, classes,
                        done="Resource updated (rows affected: {result})")
            if delete.form_submit_button("Delete resource"):
                attempt(resources.delete_resource, item["resource_id"], classes,
                        done="Resource deleted (rows affected: {result})")


def show_requests(production_id, account, classes, items):
    st.subheader("Resource requests")
    requests = schedule.list_requests(production_id)
    show_table(requests, "resource_requests", "requests")
    if can(classes, "request_resource") and items:
        events = [e for e in schedule.list_events(production_id)
                  if e["status"] not in ("Cancelled", "Completed")]
        event = pick("Event to request for", events, "request_event",
                     lambda e: f"#{e['event_id']} {e['event_type']} {e['start_datetime']:%Y-%m-%d %H:%M}")
        item = pick("Resource to request", items, "request_item",
                    lambda r: f"{r['resource_name']} ({r['status']})")
        if event and item and st.button("Send request", key="send_request"):
            attempt(schedule.request_resource, event["event_id"], item["resource_id"], classes,
                    account["person_id"], done="Request sent (rows affected: {result})")
    if can(classes, "manage_resources"):
        request = pick("Open request", requests, "decide_request",
                       lambda r: f"{r['resource_name']} for #{r['event_id']} {r['event_type']}")
        if request is None:
            return
        confirmed = st.checkbox("Confirm even if there is a clash", key="request_confirm")
        confirm, reject = st.columns(2)
        if confirm.button("Confirm request", key="confirm_request"):
            attempt(schedule.decide_request, request["event_id"], request["resource_id"], True,
                    classes, confirmed, done="Request confirmed (rows affected: {result})")
        if reject.button("Reject request", key="reject_request"):
            attempt(schedule.decide_request, request["event_id"], request["resource_id"], False,
                    classes, done="Request rejected (rows affected: {result})")


def show_issue_and_return(classes):
    st.title("Issue and return")
    manage = can(classes, "manage_resources")
    issue_tab, return_tab, out_tab, overdue_tab = st.tabs(
        ["Issue", "Return", "Currently out", "Overdue returns"]
    )
    with issue_tab:
        if not manage:
            st.info("Only the Resource Coordinator can issue items.")
        else:
            show_issue_form(classes)
    with return_tab:
        if not manage:
            st.info("Only the Resource Coordinator can record returns.")
        else:
            show_return_form(classes)
    with out_tab:
        show_table(movements.open_movements(), "items_out", "out")
    with overdue_tab:
        show_table(movements.overdue_returns(), "overdue_returns", "overdue")


def show_issue_form(classes):
    available = resources.list_resources()
    st.caption(
        "Only Available or Returned items in good condition can be issued. "
        "Damaged, Under Repair, Reserved and Issued items are refused."
    )
    people = list_people()
    names, ids = lookup(people, "person_id", "full_name")
    with st.form("issue_form"):
        item = st.selectbox(
            "Resource", range(len(available)),
            format_func=lambda i: f"{available[i]['resource_name']} ({available[i]['status']})",
        ) if available else None
        person_id = st.selectbox("Issue to", ids, format_func=names.get)
        days = st.number_input("Expected back in (days)", 1, 365, 3)
        if st.form_submit_button("Issue") and item is not None:
            now = datetime.now().replace(microsecond=0)
            attempt(movements.issue_resource, available[item]["resource_id"], person_id,
                    now + timedelta(days=days), now,
                    classes=classes, done="Issued (movement {result}, resource status set to Issued)")


def show_return_form(classes):
    out = movements.open_movements()
    with st.form("return_form"):
        movement = st.selectbox(
            "Item to return", range(len(out)),
            format_func=lambda i: f"{out[i]['resource_name']} - {out[i]['issued_to']}",
        ) if out else None
        condition = st.selectbox("Condition on return", resources.CONDITIONS)
        if st.form_submit_button("Record return") and movement is not None:
            attempt(movements.record_return, out[movement]["movement_id"], condition,
                    classes=classes, done="Return recorded, resource status is now {result}")
