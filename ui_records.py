from datetime import date

import streamlit as st

import records
from access import can
from ui_common import attempt, pick, show_table


def show_records(production, classes):
    st.title("Records")
    production_tab, venues_tab, people_tab = st.tabs(["This production", "Venues", "People"])
    with production_tab:
        show_production_editor(production, classes)
    with venues_tab:
        show_venues(classes)
    with people_tab:
        show_people(classes)


def show_production_editor(production, classes):
    if not can(classes, "manage_production"):
        st.info("Only a Producer or Administrator can edit production details.")
        return
    types = records.PRODUCTION_TYPES
    statuses = records.PRODUCTION_STATUSES
    if production["status"] == "Archived":
        st.warning("This production is archived and read-only.")
        return
    with st.form("edit_production"):
        title = st.text_input("Title", production["title"])
        production_type = st.selectbox(
            "Type", types,
            index=types.index(production["production_type"]) if production["production_type"] in types else 0,
        )
        start = st.date_input("Start", production["start_date"], key="prod_start")
        end = st.date_input("End", production["end_date"], key="prod_end")
        status = st.selectbox(
            "Status", statuses,
            index=statuses.index(production["status"]) if production["status"] in statuses else 0,
        )
        if st.form_submit_button("Save production"):
            attempt(records.update_production, production["production_id"], title, production_type,
                    start, end, status, classes, done="Production updated (rows affected: {result})")
    st.write("Archiving keeps all history but makes the production read-only.")
    if st.button("Archive this production", key="archive_production"):
        attempt(records.archive_production, production["production_id"], classes,
                done="Production archived (rows affected: {result})")


def show_new_production(classes, person_id):
    """Shown on the production list for Producers and Administrators."""
    with st.expander("Create a production"):
        with st.form("new_production", clear_on_submit=True):
            title = st.text_input("Title")
            production_type = st.selectbox("Type", records.PRODUCTION_TYPES)
            start = st.date_input("Start", date.today(), key="new_prod_start")
            end = st.date_input("End", date.today(), key="new_prod_end")
            status = st.selectbox("Status", records.PRODUCTION_STATUSES)
            if st.form_submit_button("Create"):
                attempt(records.create_production, title, production_type, start, end, status,
                        classes, person_id, done="Production {result} created")


def show_venues(classes):
    search = st.text_input("Search venues", key="venue_search")
    venues = records.list_venues(search)
    show_table(venues, "venues", "venues")
    if not can(classes, "manage_venues"):
        return
    with st.form("add_venue", clear_on_submit=True):
        name = st.text_input("Name")
        address = st.text_input("Address")
        contact = st.text_input("Contact")
        capacity = st.number_input("Capacity", min_value=1, value=100)
        if st.form_submit_button("Add venue"):
            attempt(records.add_venue, name, address, contact, int(capacity), classes,
                    done="Venue added (rows affected: {result})")
    venue = pick("Venue to edit", venues, "venue_pick", lambda v: v["venue_name"])
    if venue is not None:
        with st.form("edit_venue"):
            name = st.text_input("Name", venue["venue_name"])
            address = st.text_input("Address", venue["address"] or "")
            contact = st.text_input("Contact", venue["contact_info"] or "")
            capacity = st.number_input("Capacity", min_value=1, value=int(venue["capacity"] or 1))
            if st.form_submit_button("Save venue"):
                attempt(records.update_venue, venue["venue_id"], name, address, contact,
                        int(capacity), classes, done="Venue updated (rows affected: {result})")


def show_people(classes):
    search = st.text_input("Search people", key="people_search")
    people = records.list_people(search)
    if not can(classes, "manage_people"):
        # Contact details stay private to people who manage the team (SRS 10.2).
        people = [{"person_id": p["person_id"], "full_name": p["full_name"]} for p in people]
    show_table(people, "people", "people")
    if not can(classes, "manage_people"):
        return
    with st.form("add_person", clear_on_submit=True):
        name = st.text_input("Full name")
        email = st.text_input("Email")
        phone = st.text_input("Phone")
        if st.form_submit_button("Add person"):
            attempt(records.add_person, name, email, phone, classes,
                    done="Person added (rows affected: {result})")
    person = pick("Person to edit", people, "person_pick", lambda p: p["full_name"])
    if person is not None:
        with st.form("edit_person"):
            name = st.text_input("Full name", person["full_name"])
            email = st.text_input("Email", person["email"] or "")
            phone = st.text_input("Phone", person["phone"] or "")
            save, delete = st.columns(2)
            if save.form_submit_button("Save person"):
                attempt(records.update_person, person["person_id"], name, email, phone, classes,
                        done="Person updated (rows affected: {result})")
            if delete.form_submit_button("Delete person"):
                attempt(records.delete_person, person["person_id"], classes,
                        done="Person deleted (rows affected: {result})")


def show_my_contact(account, classes):
    """Cast / Crew edit their own phone and email only."""
    if not can(classes, "update_own_contact") or account["person_id"] is None:
        return
    me = next((p for p in records.list_people() if p["person_id"] == account["person_id"]), None)
    if me is None:
        return
    st.subheader("My contact details")
    with st.form("my_contact"):
        email = st.text_input("Email", me["email"] or "")
        phone = st.text_input("Phone", me["phone"] or "")
        if st.form_submit_button("Save my details"):
            attempt(records.update_own_contact, me["person_id"], email, phone, classes,
                    account["person_id"], done="Your details were updated (rows affected: {result})")
