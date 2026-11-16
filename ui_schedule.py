from datetime import datetime, timedelta

import streamlit as st

import resources
import schedule
from access import can
from records import list_people, list_venues
from ui_common import attempt, lookup, pick, pick_datetime, show_table


def show_schedule(production, account, classes):
    st.title("Schedule")
    production_id = production["production_id"]
    status = st.selectbox("Status", ["All", *schedule.EVENT_STATUSES], key="event_status")
    if classes == {"Cast / Crew"}:
        st.caption("Showing the events you are part of.")
        show_table(schedule.list_events(production_id, status, account["person_id"]),
                   "my_events", "my_events")
        return

    events = schedule.list_events(production_id, status)
    show_table(events, "events", "events")
    manage = can(classes, "manage_schedule")
    if not manage and not can(classes, "propose_event"):
        return
    if not manage:
        st.caption("As a Department Head you can propose events. A Producer or Stage Manager approves them.")
        show_new_event_form(production_id, classes)
        return
    new_tab, proposals_tab, manage_tab = st.tabs(["New event", "Proposals", "Change an event"])
    with new_tab:
        show_new_event_form(production_id, classes)
    with proposals_tab:
        show_proposals(events, classes)
    with manage_tab:
        event = pick("Event", events, "event_pick",
                     lambda e: f"#{e['event_id']} {e['event_type']} {e['start_datetime']:%Y-%m-%d %H:%M} ({e['status']})")
        if event is not None:
            show_reschedule(event, classes)
            show_status_change(event, classes)
            show_participants(event, classes)
            show_reservations(event, classes)


def show_proposals(events, classes):
    proposed = [e for e in events if e["status"] == "Proposed"]
    event = pick("Proposed event", proposed, "proposal_pick",
                 lambda e: f"#{e['event_id']} {e['event_type']} {e['start_datetime']:%Y-%m-%d %H:%M}")
    if event is None or not can(classes, "approve_event"):
        return
    confirmed = st.checkbox("Approve even if there are clashes", key="proposal_confirm")
    approve, decline = st.columns(2)
    if approve.button("Approve (becomes Scheduled)", key="proposal_approve"):
        attempt(schedule.propose_decision, event["event_id"], True, classes, confirmed,
                done="Proposal approved (rows affected: {result})")
    if decline.button("Decline (cancels it)", key="proposal_decline"):
        attempt(schedule.propose_decision, event["event_id"], False, classes,
                done="Proposal declined (rows affected: {result})")


def show_new_event_form(production_id, classes):
    venues = list_venues()
    venue_names, venue_ids = lookup(venues, "venue_id", "venue_name", include_none=True)
    people = list_people()
    person_names, _ = lookup(people, "person_id", "full_name")
    with st.form("new_event"):
        event_type = st.selectbox("Type", schedule.EVENT_TYPES)
        venue_id = st.selectbox("Venue", venue_ids, format_func=lambda v: venue_names.get(v, "(none)"))
        start = pick_datetime("Start", datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(days=1), "new_start")
        end = pick_datetime("End", datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(days=1, hours=2), "new_end")
        status = st.selectbox("Status", ["Scheduled", "Confirmed"]) if can(classes, "manage_schedule") else "Proposed"
        chosen = st.multiselect("People", list(person_names), format_func=person_names.get)
        notes = st.text_area("Notes")
        confirmed = st.checkbox("I have reviewed any clashes and want to save anyway", key="new_confirm")
        if st.form_submit_button("Create event"):
            attempt(schedule.create_event, production_id, venue_id, event_type, start, end,
                    status, notes, chosen, confirmed, classes=classes,
                    done="Event {result} created")


def show_reschedule(event, classes):
    st.subheader("Reschedule")
    venues = list_venues()
    venue_names, venue_ids = lookup(venues, "venue_id", "venue_name", include_none=True)
    affected = schedule.affected_by_event(event["event_id"])
    st.write(
        f"**This change affects:** {len(affected['people'])} person(s), "
        f"venue {affected['venue'] or 'none'}, {len(affected['resources'])} reserved resource(s)."
    )
    with st.expander("Show who and what is affected"):
        show_table(affected["people"], "affected_people", "aff_people")
        show_table(affected["resources"], "affected_resources", "aff_res")
    with st.form("reschedule"):
        start = pick_datetime("New start", event["start_datetime"], f"re_start_{event['event_id']}")
        end = pick_datetime("New end", event["end_datetime"], f"re_end_{event['event_id']}")
        venue_id = st.selectbox(
            "Venue", venue_ids, format_func=lambda v: venue_names.get(v, "(none)"),
            index=venue_ids.index(event["venue_id"]) if event["venue_id"] in venue_ids else 0,
        )
        confirmed = st.checkbox("I have reviewed any clashes and want to save anyway", key=f"re_confirm_{event['event_id']}")
        if st.form_submit_button("Save new time"):
            attempt(schedule.reschedule_event, event["event_id"], start, end, venue_id, confirmed,
                    classes=classes, done="Event rescheduled (rows affected: {result})")


def show_status_change(event, classes):
    st.subheader("Status")
    statuses = [x for x in schedule.EVENT_STATUSES if x != "Proposed" or event["status"] == "Proposed"]
    with st.form("event_status_form"):
        status = st.selectbox(
            "Set status", statuses, index=statuses.index(event["status"]),
        )
        confirmed = st.checkbox("Confirm even if there are clashes", key="status_confirm")
        if st.form_submit_button("Update status (Cancelled keeps the record)"):
            attempt(schedule.set_event_status, event["event_id"], status, confirmed,
                    classes=classes, done="Status updated (rows affected: {result})")


def show_participants(event, classes):
    st.subheader("People")
    show_table(schedule.event_people(event["event_id"]), "participants", "participants")
    people = list_people()
    names, ids = lookup(people, "person_id", "full_name")
    with st.form("add_participant"):
        person_id = st.selectbox("Person", ids, format_func=names.get)
        status = st.selectbox("Participation", schedule.PARTICIPATION_STATUSES)
        confirmed = st.checkbox("Add even if this person has a clash", key="person_confirm")
        add, remove = st.columns(2)
        if add.form_submit_button("Add or update"):
            attempt(schedule.add_participant, event["event_id"], person_id, status, confirmed,
                    classes=classes, done="Participant saved (rows affected: {result})")
        if remove.form_submit_button("Remove"):
            attempt(schedule.remove_participant, event["event_id"], person_id, classes,
                    done="Participant removed (rows affected: {result})")


def show_reservations(event, classes):
    st.subheader("Resource reservations")
    show_table(schedule.event_resources(event["event_id"]), "reservations", "reservations")
    if not can(classes, "reserve_resource"):
        return
    items = resources.list_resources()
    with st.form("reserve_resource"):
        item = st.selectbox(
            "Resource", range(len(items)),
            format_func=lambda i: f"{items[i]['resource_name']} ({items[i]['status']})",
        )
        status = st.selectbox("Reservation status", schedule.RESERVATION_STATUSES, index=1)
        confirmed = st.checkbox("Reserve even if this resource has a clash", key="res_confirm")
        if st.form_submit_button("Reserve or update"):
            attempt(schedule.reserve_resource, event["event_id"], items[item]["resource_id"],
                    status, confirmed,
                    classes=classes, done="Reservation saved (rows affected: {result})")
