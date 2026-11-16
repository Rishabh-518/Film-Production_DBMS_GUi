from datetime import time

import streamlit as st

import callsheets
import schedule
from access import can
from ui_common import attempt, pick, show_table


def show_call_sheets(production, account, classes):
    st.title("Call sheets")
    production_id = production["production_id"]
    person_id = account["person_id"]

    if person_id is not None and can(classes, "acknowledge_call_sheet"):
        st.subheader("Your call sheets")
        mine = callsheets.sheets_for_person(production_id, person_id)
        show_table(mine, "my_call_sheets", "my_sheets")
        waiting = [s for s in mine if s["acknowledged_at"] is None]
        sheet = pick("Acknowledge", waiting, "ack_pick",
                     lambda s: f"{s['event_type']} on {s['call_date']} (revision {s['revision_no']})")
        if sheet is not None and st.button("Acknowledge call sheet", key="ack_button"):
            attempt(callsheets.acknowledge, sheet["sheet_id"], person_id, classes,
                    done="Call sheet acknowledged (rows affected: {result})")

    if classes == {"Cast / Crew"}:
        return

    sheets = callsheets.list_call_sheets(production_id)
    st.subheader("All call sheets")
    show_table(sheets, "call_sheets", "sheets")

    if can(classes, "manage_call_sheets"):
        generate_tab, issue_tab = st.tabs(["Generate from an event", "Issue a draft"])
        with generate_tab:
            events = [e for e in schedule.list_events(production_id)
                      if e["status"] not in ("Cancelled", "Proposed")]
            event = pick("Event", events, "sheet_event",
                         lambda e: f"#{e['event_id']} {e['event_type']} {e['start_datetime']:%Y-%m-%d %H:%M}")
            reporting = st.time_input("Reporting time", time(8, 0), key="sheet_time")
            if event is not None and st.button("Generate new revision", key="generate_sheet"):
                attempt(callsheets.generate_call_sheet, event["event_id"], classes, reporting,
                        done="Call sheet {result} created as a Draft")
        with issue_tab:
            drafts = [s for s in sheets if s["status"] == "Draft"]
            draft = pick("Draft", drafts, "sheet_draft",
                         lambda s: f"Sheet {s['sheet_id']}: {s['event_type']} revision {s['revision_no']}")
            if draft is not None and st.button("Issue this revision", key="issue_sheet"):
                attempt(callsheets.issue_call_sheet, draft["sheet_id"], classes,
                        done="Issued. Older revisions superseded: {result}")

    st.subheader("View a call sheet")
    chosen = pick("Call sheet", sheets, "sheet_view",
                  lambda s: f"Sheet {s['sheet_id']}: {s['event_type']} revision {s['revision_no']} ({s['status']})")
    if chosen is not None:
        details = callsheets.sheet_details(chosen["sheet_id"])
        st.write(
            f"**{details['production']}** - {details['event_type']} on {details['call_date']}, "
            f"report at **{details['reporting_time']}**. Venue: {details['venue_name'] or 'TBA'}. "
            f"Revision {details['revision_no']} ({details['status']})."
        )
        show_table(details["people"], "call_sheet_people", "sheet_people")
        show_table(details["resources"], "call_sheet_resources", "sheet_resources")

    st.subheader("Not yet acknowledged")
    show_table(callsheets.not_acknowledged(production_id), "not_acknowledged", "not_ack")
