"""Events, who is in them, which resources they reserve, and clash detection."""
from psycopg2.errors import RaiseException

from access import ClashError, RuleError, can, check_production_open, require
from db import transaction

EVENT_TYPES = [
    "Rehearsal", "Technical Rehearsal", "Shoot Day", "Performance", "Screening",
    "Production Meeting", "Audition", "Location Visit", "Editing Milestone",
]
# Proposed is what a Department Head creates; a Producer or Stage Manager approves it.
EVENT_STATUSES = ["Proposed", "Scheduled", "Confirmed", "Completed", "Cancelled"]
PARTICIPATION_STATUSES = ["Assigned", "Present", "Absent", "Unavailable"]
RESERVATION_STATUSES = ["Tentative", "Confirmed", "Cancelled"]
# A request holds nothing until the Resource Coordinator confirms it.
NOT_HOLDING = ("Cancelled", "Requested", "Rejected")
UNUSABLE_RESOURCE_STATUSES = ("Damaged", "Under Repair")


def list_events(production_id, status="All", person_id=None):
    """With a person_id, only the events that person takes part in (Cast / Crew)."""
    with transaction() as cur:
        cur.execute(
            """
            SELECT e.event_id, e.event_type, e.start_datetime, e.end_datetime, e.status,
                   v.venue_name, e.venue_id, e.hosting_notes
            FROM ProductionEvent e
            LEFT JOIN Venue v ON v.venue_id = e.venue_id
            WHERE e.production_id = %s AND (%s = 'All' OR e.status = %s)
              AND (%s::INT IS NULL OR EXISTS (
                   SELECT 1 FROM EventParticipation ep
                   WHERE ep.event_id = e.event_id AND ep.person_id = %s::INT))
            ORDER BY e.start_datetime
            """,
            (production_id, status, status, person_id, person_id),
        )
        return cur.fetchall()


def get_event(event_id):
    with transaction() as cur:
        cur.execute(
            """
            SELECT e.*, v.venue_name FROM ProductionEvent e
            LEFT JOIN Venue v ON v.venue_id = e.venue_id
            WHERE e.event_id = %s
            """,
            (event_id,),
        )
        return cur.fetchone()


def event_people(event_id):
    with transaction() as cur:
        cur.execute(
            """
            SELECT per.person_id, per.full_name, ep.participation_status
            FROM EventParticipation ep JOIN Person per ON per.person_id = ep.person_id
            WHERE ep.event_id = %s ORDER BY per.full_name
            """,
            (event_id,),
        )
        return cur.fetchall()


def event_resources(event_id):
    with transaction() as cur:
        cur.execute(
            """
            SELECT r.resource_id, r.resource_name, r.status AS resource_status,
                   er.reservation_status, er.reserved_at
            FROM EventResourceReservation er JOIN Resource r ON r.resource_id = er.resource_id
            WHERE er.event_id = %s ORDER BY r.resource_name
            """,
            (event_id,),
        )
        return cur.fetchall()


def production_of_event(cur, event_id):
    cur.execute("SELECT production_id FROM ProductionEvent WHERE event_id = %s", (event_id,))
    row = cur.fetchone()
    if row is None:
        raise RuleError("That event does not exist.")
    return row["production_id"]


def find_clashes(cur, start, end, venue_id, person_ids, resource_ids, ignore_event_id=None):
    """Other live events that overlap [start, end) and share a person, venue or resource.

    Two time ranges overlap when each starts before the other ends.
    """
    cur.execute(
        """
        SELECT 'Person' AS kind, per.full_name AS name, e.event_id, e.event_type,
               p.title AS production, e.start_datetime, e.end_datetime
        FROM EventParticipation ep
        JOIN ProductionEvent e ON e.event_id = ep.event_id
        JOIN Production p ON p.production_id = e.production_id
        JOIN Person per ON per.person_id = ep.person_id
        WHERE ep.person_id = ANY(%(people)s)
          AND ep.participation_status IS DISTINCT FROM 'Unavailable'
          AND e.status IS DISTINCT FROM 'Cancelled'
          AND e.event_id IS DISTINCT FROM %(ignore)s
          AND e.start_datetime < %(end)s AND e.end_datetime > %(start)s
        UNION ALL
        SELECT 'Venue', v.venue_name, e.event_id, e.event_type, p.title,
               e.start_datetime, e.end_datetime
        FROM ProductionEvent e
        JOIN Venue v ON v.venue_id = e.venue_id
        JOIN Production p ON p.production_id = e.production_id
        WHERE e.venue_id = %(venue)s
          AND e.status IS DISTINCT FROM 'Cancelled'
          AND e.event_id IS DISTINCT FROM %(ignore)s
          AND e.start_datetime < %(end)s AND e.end_datetime > %(start)s
        UNION ALL
        SELECT 'Resource', r.resource_name, e.event_id, e.event_type, p.title,
               e.start_datetime, e.end_datetime
        FROM EventResourceReservation er
        JOIN ProductionEvent e ON e.event_id = er.event_id
        JOIN Production p ON p.production_id = e.production_id
        JOIN Resource r ON r.resource_id = er.resource_id
        WHERE er.resource_id = ANY(%(resources)s)
          AND COALESCE(er.reservation_status, '') <> ALL(%(not_holding)s)
          AND e.status IS DISTINCT FROM 'Cancelled'
          AND e.event_id IS DISTINCT FROM %(ignore)s
          AND e.start_datetime < %(end)s AND e.end_datetime > %(start)s
        ORDER BY start_datetime
        """,
        {"start": start, "end": end, "venue": venue_id, "people": list(person_ids),
         "resources": list(resource_ids), "ignore": ignore_event_id,
         "not_holding": list(NOT_HOLDING)},
    )
    return cur.fetchall()


def clashes_for_event(cur, event_id, start, end, venue_id):
    """Clashes of an existing event's own people and resources at a proposed time."""
    cur.execute(
        "SELECT person_id FROM EventParticipation WHERE event_id = %s", (event_id,)
    )
    people = [row["person_id"] for row in cur.fetchall()]
    cur.execute(
        "SELECT resource_id FROM EventResourceReservation "
        "WHERE event_id = %s AND reservation_status <> ALL(%s)",
        (event_id, list(NOT_HOLDING)),
    )
    resources = [row["resource_id"] for row in cur.fetchall()]
    return find_clashes(cur, start, end, venue_id, people, resources, event_id)


def check_times(start, end):
    if end <= start:
        raise RuleError("The event must end after it starts.")


def create_event(production_id, venue_id, event_type, start, end, status="Scheduled",
                 notes="", person_ids=(), confirmed=False, *, classes):
    """Return the new event_id. Raises ClashError unless the user confirmed the clashes.

    A Department Head can only propose: whatever status is asked for, it is saved as Proposed.
    """
    if not can(classes, "manage_schedule"):
        require(classes, "propose_event")
        status = "Proposed"
    check_times(start, end)
    with transaction() as cur:
        check_production_open(cur, production_id)
        clashes = find_clashes(cur, start, end, venue_id, person_ids, [])
        if clashes and not confirmed:
            raise ClashError(clashes)
        cur.execute(
            """
            INSERT INTO ProductionEvent (event_id, production_id, venue_id, event_type,
                                         start_datetime, end_datetime, status, hosting_notes)
            SELECT COALESCE(MAX(event_id), 0) + 1, %s, %s, %s, %s, %s, %s, %s
            FROM ProductionEvent
            RETURNING event_id
            """,
            (production_id, venue_id, event_type, start, end, status, notes),
        )
        event_id = cur.fetchone()["event_id"]
        # Event and its people are saved together, or not at all.
        for person_id in person_ids:
            cur.execute(
                "INSERT INTO EventParticipation (event_id, person_id, participation_status) "
                "VALUES (%s, %s, 'Assigned')",
                (event_id, person_id),
            )
        return event_id


def affected_by_event(event_id):
    """Everyone and everything that a change to this event touches."""
    return {
        "people": event_people(event_id),
        "venue": get_event(event_id)["venue_name"],
        "resources": event_resources(event_id),
    }


def reschedule_event(event_id, start, end, venue_id, confirmed=False, *, classes):
    require(classes, "manage_schedule")
    check_times(start, end)
    with transaction() as cur:
        check_production_open(cur, production_of_event(cur, event_id))
        clashes = clashes_for_event(cur, event_id, start, end, venue_id)
        if clashes and not confirmed:
            raise ClashError(clashes)
        cur.execute(
            "UPDATE ProductionEvent SET start_datetime = %s, end_datetime = %s, venue_id = %s "
            "WHERE event_id = %s",
            (start, end, venue_id, event_id),
        )
        return cur.rowcount


def set_event_status(event_id, status, confirmed=False, *, classes):
    """Cancelling is a status change, so the history stays. Confirming re-checks clashes."""
    require(classes, "manage_schedule")
    if status == "Proposed":
        raise RuleError("Only a Department Head's new event starts as Proposed.")
    with transaction() as cur:
        check_production_open(cur, production_of_event(cur, event_id))
        if status == "Confirmed":
            event = get_event_in(cur, event_id)
            clashes = clashes_for_event(
                cur, event_id, event["start_datetime"], event["end_datetime"], event["venue_id"]
            )
            if clashes and not confirmed:
                raise ClashError(clashes)
        cur.execute(
            "UPDATE ProductionEvent SET status = %s WHERE event_id = %s", (status, event_id)
        )
        return cur.rowcount


def get_event_in(cur, event_id):
    cur.execute("SELECT * FROM ProductionEvent WHERE event_id = %s", (event_id,))
    return cur.fetchone()


def add_participant(event_id, person_id, status="Assigned", confirmed=False, *, classes):
    require(classes, "manage_schedule")
    with transaction() as cur:
        check_production_open(cur, production_of_event(cur, event_id))
        event = get_event_in(cur, event_id)
        clashes = find_clashes(
            cur, event["start_datetime"], event["end_datetime"], None, [person_id], [], event_id
        )
        if clashes and not confirmed:
            raise ClashError(clashes)
        cur.execute(
            """
            INSERT INTO EventParticipation (event_id, person_id, participation_status)
            VALUES (%s, %s, %s)
            ON CONFLICT (event_id, person_id) DO UPDATE SET participation_status = EXCLUDED.participation_status
            """,
            (event_id, person_id, status),
        )
        return cur.rowcount


def remove_participant(event_id, person_id, classes):
    require(classes, "manage_schedule")
    with transaction() as cur:
        check_production_open(cur, production_of_event(cur, event_id))
        cur.execute(
            "DELETE FROM EventParticipation WHERE event_id = %s AND person_id = %s",
            (event_id, person_id),
        )
        return cur.rowcount


def check_usable(item):
    if item is None:
        raise RuleError("That resource does not exist.")
    unusable = {item["status"], item["resource_condition"]} & set(UNUSABLE_RESOURCE_STATUSES)
    if unusable:
        raise RuleError(f"{item['resource_name']} is {sorted(unusable)[0]} and cannot be confirmed.")


def reserve_resource(event_id, resource_id, status="Confirmed", confirmed=False, *, classes):
    """Damaged and under-repair items can never be confirmed (SRS section 4)."""
    require(classes, "reserve_resource")
    with transaction() as cur:
        check_production_open(cur, production_of_event(cur, event_id))
        cur.execute(
            "SELECT resource_name, status, resource_condition FROM Resource WHERE resource_id = %s",
            (resource_id,),
        )
        item = cur.fetchone()
        if item is None:
            raise RuleError("That resource does not exist.")
        if status == "Confirmed":
            check_usable(item)
        event = get_event_in(cur, event_id)
        clashes = find_clashes(
            cur, event["start_datetime"], event["end_datetime"], None, [], [resource_id], event_id
        )
        if clashes and not confirmed:
            raise ClashError(clashes)
        try:
            cur.execute(
                """
                INSERT INTO EventResourceReservation (event_id, resource_id, reserved_at, reservation_status)
                VALUES (%s, %s, NOW(), %s)
                ON CONFLICT (event_id, resource_id)
                DO UPDATE SET reservation_status = EXCLUDED.reservation_status, reserved_at = NOW()
                """,
                (event_id, resource_id, status),
            )
        except RaiseException as err:
            # The Lab 10A Q30 trigger, if it is installed, says the same thing.
            raise RuleError(str(err).splitlines()[0]) from None
        return cur.rowcount


def propose_decision(event_id, approve, classes, confirmed=False):
    """Producer or Stage Management turn a proposal into Scheduled, or cancel it."""
    require(classes, "approve_event")
    with transaction() as cur:
        check_production_open(cur, production_of_event(cur, event_id))
        event = get_event_in(cur, event_id)
        if event["status"] != "Proposed":
            raise RuleError("Only a proposed event can be approved or declined.")
        if approve:
            clashes = clashes_for_event(
                cur, event_id, event["start_datetime"], event["end_datetime"], event["venue_id"]
            )
            if clashes and not confirmed:
                raise ClashError(clashes)
        cur.execute(
            "UPDATE ProductionEvent SET status = %s WHERE event_id = %s",
            ("Scheduled" if approve else "Cancelled", event_id),
        )
        return cur.rowcount


def is_assigned(cur, production_id, person_id):
    cur.execute(
        "SELECT 1 FROM RoleAssignment WHERE production_id = %s AND person_id = %s LIMIT 1",
        (production_id, person_id),
    )
    return cur.fetchone() is not None


def request_resource(event_id, resource_id, classes, person_id):
    """Dept Head or Cast / Crew ask for a resource; nothing is held until it is confirmed."""
    require(classes, "request_resource")
    with transaction() as cur:
        production_id = production_of_event(cur, event_id)
        check_production_open(cur, production_id)
        if not is_assigned(cur, production_id, person_id):
            raise RuleError("You can only request resources for a production you are assigned to.")
        cur.execute("SELECT 1 FROM Resource WHERE resource_id = %s", (resource_id,))
        if cur.fetchone() is None:
            raise RuleError("That resource does not exist.")
        cur.execute(
            "SELECT reservation_status FROM EventResourceReservation "
            "WHERE event_id = %s AND resource_id = %s",
            (event_id, resource_id),
        )
        existing = cur.fetchone()
        if existing and existing["reservation_status"] not in ("Cancelled", "Rejected"):
            raise RuleError(f"This resource is already {existing['reservation_status']} for the event.")
        cur.execute(
            """
            INSERT INTO EventResourceReservation (event_id, resource_id, reserved_at, reservation_status)
            VALUES (%s, %s, NOW(), 'Requested')
            ON CONFLICT (event_id, resource_id)
            DO UPDATE SET reservation_status = 'Requested', reserved_at = NOW()
            """,
            (event_id, resource_id),
        )
        return cur.rowcount


def list_requests(production_id, status="Requested"):
    with transaction() as cur:
        cur.execute(
            """
            SELECT er.event_id, er.resource_id, e.event_type, e.start_datetime,
                   r.resource_name, r.status AS resource_status, er.reservation_status,
                   er.reserved_at
            FROM EventResourceReservation er
            JOIN ProductionEvent e ON e.event_id = er.event_id
            JOIN Resource r ON r.resource_id = er.resource_id
            WHERE e.production_id = %s AND er.reservation_status = %s
            ORDER BY er.reserved_at
            """,
            (production_id, status),
        )
        return cur.fetchall()


def decide_request(event_id, resource_id, confirm, classes, confirmed=False):
    """Confirm applies the same unusable-item and clash checks as a direct reservation."""
    require(classes, "manage_resources")
    with transaction() as cur:
        check_production_open(cur, production_of_event(cur, event_id))
        cur.execute(
            "SELECT reservation_status FROM EventResourceReservation "
            "WHERE event_id = %s AND resource_id = %s FOR UPDATE",
            (event_id, resource_id),
        )
        request = cur.fetchone()
        if request is None or request["reservation_status"] != "Requested":
            raise RuleError("There is no open request for this resource and event.")
        if confirm:
            cur.execute(
                "SELECT resource_name, status, resource_condition FROM Resource "
                "WHERE resource_id = %s",
                (resource_id,),
            )
            check_usable(cur.fetchone())
            event = get_event_in(cur, event_id)
            clashes = find_clashes(
                cur, event["start_datetime"], event["end_datetime"], None, [], [resource_id],
                event_id,
            )
            if clashes and not confirmed:
                raise ClashError(clashes)
        cur.execute(
            "UPDATE EventResourceReservation SET reservation_status = %s "
            "WHERE event_id = %s AND resource_id = %s",
            ("Confirmed" if confirm else "Rejected", event_id, resource_id),
        )
        return cur.rowcount
