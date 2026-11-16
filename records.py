"""Productions, venues and people."""
from psycopg2.errors import ForeignKeyViolation, UniqueViolation

from access import RuleError, check_production_open, require
from db import transaction

PRODUCTION_TYPES = ["Film", "Short Film", "Play", "Musical"]
PRODUCTION_STATUSES = [
    "Planning", "Pre-production", "Rehearsal", "Shooting", "Post-production", "Completed",
]


def check_dates(start_date, end_date):
    if start_date and end_date and end_date < start_date:
        raise RuleError("The end date cannot be before the start date.")


def create_production(title, production_type, start_date, end_date, status, classes,
                      producer_person_id=None):
    """The producer is a role assignment (SRS 4), saved together with the production."""
    require(classes, "manage_production")
    if not title.strip():
        raise RuleError("A production needs a title.")
    check_dates(start_date, end_date)
    with transaction() as cur:
        cur.execute(
            """
            INSERT INTO Production (production_id, title, production_type, start_date,
                                    end_date, status)
            SELECT COALESCE(MAX(production_id), 0) + 1, %s, %s, %s, %s, %s FROM Production
            RETURNING production_id
            """,
            (title.strip(), production_type, start_date, end_date, status),
        )
        production_id = cur.fetchone()["production_id"]
        if producer_person_id is not None:
            cur.execute(
                """
                INSERT INTO RoleAssignment (assignment_id, production_id, person_id, role_name,
                                            start_date, end_date)
                SELECT COALESCE(MAX(assignment_id), 0) + 1, %s, %s, 'Producer', %s, %s
                FROM RoleAssignment
                """,
                (production_id, producer_person_id, start_date, end_date),
            )
        return production_id


def update_production(production_id, title, production_type, start_date, end_date, status,
                      classes):
    require(classes, "manage_production")
    check_dates(start_date, end_date)
    with transaction() as cur:
        check_production_open(cur, production_id)
        cur.execute(
            """
            UPDATE Production
            SET title = %s, production_type = %s, start_date = %s, end_date = %s, status = %s
            WHERE production_id = %s
            """,
            (title.strip(), production_type, start_date, end_date, status, production_id),
        )
        return cur.rowcount


def archive_production(production_id, classes):
    """Archiving is a status change, so nothing is deleted."""
    require(classes, "manage_production")
    with transaction() as cur:
        check_production_open(cur, production_id)
        cur.execute(
            "UPDATE Production SET status = 'Archived' WHERE production_id = %s", (production_id,)
        )
        return cur.rowcount


def list_venues(search=""):
    with transaction() as cur:
        cur.execute(
            "SELECT venue_id, venue_name, address, contact_info, capacity FROM Venue "
            "WHERE venue_name ILIKE %s ORDER BY venue_name",
            (f"%{search.strip()}%",),
        )
        return cur.fetchall()


def add_venue(name, address, contact_info, capacity, classes):
    require(classes, "manage_venues")
    if not name.strip():
        raise RuleError("A venue needs a name.")
    if capacity is not None and capacity <= 0:
        raise RuleError("Capacity must be a positive number.")
    with transaction() as cur:
        cur.execute(
            """
            INSERT INTO Venue (venue_id, venue_name, address, contact_info, capacity)
            SELECT COALESCE(MAX(venue_id), 0) + 1, %s, %s, %s, %s FROM Venue
            """,
            (name.strip(), address, contact_info, capacity),
        )
        return cur.rowcount


def update_venue(venue_id, name, address, contact_info, capacity, classes):
    require(classes, "manage_venues")
    if capacity is not None and capacity <= 0:
        raise RuleError("Capacity must be a positive number.")
    with transaction() as cur:
        cur.execute(
            "UPDATE Venue SET venue_name = %s, address = %s, contact_info = %s, capacity = %s "
            "WHERE venue_id = %s",
            (name.strip(), address, contact_info, capacity, venue_id),
        )
        return cur.rowcount


def list_people(search=""):
    with transaction() as cur:
        cur.execute(
            "SELECT person_id, full_name, email, phone FROM Person "
            "WHERE full_name ILIKE %s OR email ILIKE %s ORDER BY full_name",
            (f"%{search.strip()}%", f"%{search.strip()}%"),
        )
        return cur.fetchall()


def add_person(full_name, email, phone, classes):
    require(classes, "manage_people")
    if not full_name.strip():
        raise RuleError("A person needs a name.")
    try:
        with transaction() as cur:
            cur.execute(
                """
                INSERT INTO Person (person_id, full_name, email, phone)
                SELECT COALESCE(MAX(person_id), 0) + 1, %s, %s, %s FROM Person
                """,
                (full_name.strip(), email.strip().lower() or None, phone.strip()),
            )
            return cur.rowcount
    except UniqueViolation:
        raise RuleError("Another person already uses that email address.") from None


def update_person(person_id, full_name, email, phone, classes):
    require(classes, "manage_people")
    try:
        with transaction() as cur:
            cur.execute(
                "UPDATE Person SET full_name = %s, email = %s, phone = %s WHERE person_id = %s",
                (full_name.strip(), email.strip().lower() or None, phone.strip(), person_id),
            )
            return cur.rowcount
    except UniqueViolation:
        raise RuleError("Another person already uses that email address.") from None


def update_own_contact(person_id, email, phone, classes, acting_person_id):
    """Self-service: Cast / Crew change only their own phone and email, never their name."""
    require(classes, "update_own_contact")
    if person_id != acting_person_id:
        raise RuleError("You can only change your own contact details.")
    try:
        with transaction() as cur:
            cur.execute(
                "UPDATE Person SET email = %s, phone = %s WHERE person_id = %s",
                (email.strip().lower() or None, phone.strip(), person_id),
            )
            return cur.rowcount
    except UniqueViolation:
        raise RuleError("Another person already uses that email address.") from None


def delete_person(person_id, classes):
    require(classes, "manage_people")
    try:
        with transaction() as cur:
            cur.execute("DELETE FROM Person WHERE person_id = %s", (person_id,))
            return cur.rowcount
    except ForeignKeyViolation:
        raise RuleError(
            "This person has roles, tasks, events or movements, so they can't be deleted."
        ) from None
