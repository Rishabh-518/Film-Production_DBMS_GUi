"""Call sheets: generated from the schedule, numbered by revision, acknowledged by recipients."""
from access import RuleError, check_production_open, require
from db import transaction


def list_call_sheets(production_id):
    with transaction() as cur:
        cur.execute(
            """
            SELECT cs.sheet_id, cs.event_id, e.event_type, cs.call_date, cs.reporting_time,
                   cs.revision_no, cs.status
            FROM CallSheet cs JOIN ProductionEvent e ON e.event_id = cs.event_id
            WHERE e.production_id = %s
            ORDER BY cs.call_date DESC, cs.event_id, cs.revision_no DESC
            """,
            (production_id,),
        )
        return cur.fetchall()


def generate_call_sheet(event_id, classes, reporting_time=None):
    """Create the next numbered revision as a Draft. Earlier revisions are kept."""
    require(classes, "manage_call_sheets")
    with transaction() as cur:
        cur.execute(
            "SELECT production_id, start_datetime, status FROM ProductionEvent WHERE event_id = %s",
            (event_id,),
        )
        event = cur.fetchone()
        if event is None:
            raise RuleError("That event does not exist.")
        check_production_open(cur, event["production_id"])
        if event["status"] == "Cancelled":
            raise RuleError("A cancelled event does not need a call sheet.")
        if event["status"] == "Proposed":
            raise RuleError("A proposed event must be approved before it gets a call sheet.")
        reporting_time = reporting_time or event["start_datetime"].time().replace(second=0)
        cur.execute(
            """
            INSERT INTO CallSheet (sheet_id, event_id, call_date, reporting_time, revision_no, status)
            SELECT (SELECT COALESCE(MAX(sheet_id), 0) + 1 FROM CallSheet), %s, %s, %s,
                   COALESCE(MAX(revision_no), 0) + 1, 'Draft'
            FROM CallSheet WHERE event_id = %s
            RETURNING sheet_id
            """,
            (event_id, event["start_datetime"].date(), reporting_time, event_id),
        )
        return cur.fetchone()["sheet_id"]


def issue_call_sheet(sheet_id, classes):
    """Issue this revision and supersede the older ones in one step."""
    require(classes, "manage_call_sheets")
    with transaction() as cur:
        cur.execute(
            """
            SELECT cs.event_id, cs.status, e.production_id
            FROM CallSheet cs JOIN ProductionEvent e ON e.event_id = cs.event_id
            WHERE cs.sheet_id = %s FOR UPDATE OF cs
            """,
            (sheet_id,),
        )
        sheet = cur.fetchone()
        if sheet is None:
            raise RuleError("That call sheet does not exist.")
        check_production_open(cur, sheet["production_id"])
        if sheet["status"] != "Draft":
            raise RuleError(f"Only a Draft can be issued; this one is {sheet['status']}.")
        cur.execute(
            "UPDATE CallSheet SET status = 'Superseded' "
            "WHERE event_id = %s AND status = 'Issued'",
            (sheet["event_id"],),
        )
        superseded = cur.rowcount
        cur.execute("UPDATE CallSheet SET status = 'Issued' WHERE sheet_id = %s", (sheet_id,))
        return superseded


def sheet_details(sheet_id):
    """Everything printed on a call sheet: event, venue, people with ack state, resources."""
    with transaction() as cur:
        cur.execute(
            """
            SELECT cs.sheet_id, cs.revision_no, cs.status, cs.call_date, cs.reporting_time,
                   e.event_id, e.event_type, e.start_datetime, e.end_datetime,
                   v.venue_name, v.address, p.title AS production
            FROM CallSheet cs
            JOIN ProductionEvent e ON e.event_id = cs.event_id
            JOIN Production p ON p.production_id = e.production_id
            LEFT JOIN Venue v ON v.venue_id = e.venue_id
            WHERE cs.sheet_id = %s
            """,
            (sheet_id,),
        )
        sheet = cur.fetchone()
        if sheet is None:
            return None
        cur.execute(
            """
            SELECT per.person_id, per.full_name,
                   COALESCE(string_agg(DISTINCT ra.role_name, ', '), '') AS roles,
                   ack.acknowledged_at
            FROM CallSheet cs
            JOIN EventParticipation ep ON ep.event_id = cs.event_id
            JOIN Person per ON per.person_id = ep.person_id
            LEFT JOIN RoleAssignment ra ON ra.person_id = per.person_id
                 AND ra.production_id = (SELECT production_id FROM ProductionEvent
                                         WHERE event_id = cs.event_id)
            LEFT JOIN CallSheetAcknowledgement ack
                 ON ack.sheet_id = cs.sheet_id AND ack.person_id = per.person_id
            WHERE cs.sheet_id = %s AND ep.participation_status IS DISTINCT FROM 'Unavailable'
            GROUP BY per.person_id, per.full_name, ack.acknowledged_at
            ORDER BY per.full_name
            """,
            (sheet_id,),
        )
        sheet["people"] = cur.fetchall()
        cur.execute(
            """
            SELECT r.resource_name, r.resource_type, er.reservation_status
            FROM EventResourceReservation er JOIN Resource r ON r.resource_id = er.resource_id
            WHERE er.event_id = %s AND er.reservation_status <> 'Cancelled'
            ORDER BY r.resource_name
            """,
            (sheet["event_id"],),
        )
        sheet["resources"] = cur.fetchall()
        return sheet


def acknowledge(sheet_id, person_id, classes):
    """Cast and crew confirm they have seen an issued call sheet meant for them."""
    require(classes, "acknowledge_call_sheet")
    with transaction() as cur:
        cur.execute(
            """
            SELECT cs.status, EXISTS (
                SELECT 1 FROM EventParticipation ep
                WHERE ep.event_id = cs.event_id AND ep.person_id = %s) AS is_recipient
            FROM CallSheet cs WHERE cs.sheet_id = %s
            """,
            (person_id, sheet_id),
        )
        sheet = cur.fetchone()
        if sheet is None:
            raise RuleError("That call sheet does not exist.")
        if sheet["status"] != "Issued":
            raise RuleError("Only an issued call sheet can be acknowledged.")
        if not sheet["is_recipient"]:
            raise RuleError("This call sheet is not addressed to you.")
        cur.execute(
            """
            INSERT INTO CallSheetAcknowledgement (sheet_id, person_id, acknowledged_at)
            VALUES (%s, %s, NOW()) ON CONFLICT (sheet_id, person_id) DO NOTHING
            """,
            (sheet_id, person_id),
        )
        return cur.rowcount


def not_acknowledged(production_id):
    """People who were sent an issued call sheet and have not acknowledged it."""
    with transaction() as cur:
        cur.execute(
            """
            SELECT cs.sheet_id, cs.revision_no, e.event_type, cs.call_date,
                   per.full_name, per.phone
            FROM CallSheet cs
            JOIN ProductionEvent e ON e.event_id = cs.event_id
            JOIN EventParticipation ep ON ep.event_id = e.event_id
            JOIN Person per ON per.person_id = ep.person_id
            WHERE e.production_id = %s AND cs.status = 'Issued'
              AND ep.participation_status IS DISTINCT FROM 'Unavailable'
              AND NOT EXISTS (SELECT 1 FROM CallSheetAcknowledgement ack
                              WHERE ack.sheet_id = cs.sheet_id AND ack.person_id = per.person_id)
            ORDER BY cs.call_date, per.full_name
            """,
            (production_id,),
        )
        return cur.fetchall()


def sheets_for_person(production_id, person_id):
    with transaction() as cur:
        cur.execute(
            """
            SELECT cs.sheet_id, e.event_type, cs.call_date, cs.reporting_time, cs.revision_no,
                   ack.acknowledged_at
            FROM CallSheet cs
            JOIN ProductionEvent e ON e.event_id = cs.event_id
            JOIN EventParticipation ep ON ep.event_id = e.event_id AND ep.person_id = %s
            LEFT JOIN CallSheetAcknowledgement ack
                 ON ack.sheet_id = cs.sheet_id AND ack.person_id = %s
            WHERE e.production_id = %s AND cs.status = 'Issued'
            ORDER BY cs.call_date DESC
            """,
            (person_id, person_id, production_id),
        )
        return cur.fetchall()
