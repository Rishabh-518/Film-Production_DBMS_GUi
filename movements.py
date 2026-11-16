"""Issuing resources to people and taking them back."""
from datetime import datetime

from access import RuleError, require
from db import transaction

# Reserved items belong to an event, so they are not handed out as spares.
ISSUABLE_STATUSES = ("Available", "Returned")
BAD_CONDITIONS = ("Damaged", "Under Repair")


def issue_resource(resource_id, person_id, expected_return, issued_at=None, *, classes):
    """Write the movement and mark the item Issued, or do neither."""
    require(classes, "manage_resources")
    issued_at = issued_at or datetime.now().replace(microsecond=0)
    if expected_return < issued_at:
        raise RuleError("The expected return cannot be before the issue time.")
    with transaction() as cur:
        cur.execute(
            "SELECT resource_name, status, resource_condition FROM Resource "
            "WHERE resource_id = %s FOR UPDATE",
            (resource_id,),
        )
        item = cur.fetchone()
        if item is None:
            raise RuleError("That resource does not exist.")
        if item["status"] not in ISSUABLE_STATUSES:
            raise RuleError(f"{item['resource_name']} is {item['status']} and cannot be issued.")
        if item["resource_condition"] in BAD_CONDITIONS:
            raise RuleError(
                f"{item['resource_name']} is in {item['resource_condition']} condition "
                "and cannot be issued."
            )
        # Status first: if the movement insert then fails, the rollback undoes both.
        cur.execute(
            "UPDATE Resource SET status = 'Issued' WHERE resource_id = %s", (resource_id,)
        )
        cur.execute(
            """
            INSERT INTO ResourceMovement (movement_id, resource_id, person_id,
                                          issue_datetime, expected_return)
            SELECT COALESCE(MAX(movement_id), 0) + 1, %s, %s, %s, %s FROM ResourceMovement
            RETURNING movement_id
            """,
            (resource_id, person_id, issued_at, expected_return),
        )
        return cur.fetchone()["movement_id"]


def record_return(movement_id, return_condition, returned_at=None, *, classes):
    require(classes, "manage_resources")
    returned_at = returned_at or datetime.now().replace(microsecond=0)
    with transaction() as cur:
        cur.execute(
            "SELECT resource_id, issue_datetime, actual_return FROM ResourceMovement "
            "WHERE movement_id = %s FOR UPDATE",
            (movement_id,),
        )
        movement = cur.fetchone()
        if movement is None:
            raise RuleError("That movement does not exist.")
        if movement["actual_return"] is not None:
            raise RuleError("This item has already been returned.")
        if returned_at < movement["issue_datetime"]:
            raise RuleError("An item cannot be returned before it was issued.")
        cur.execute(
            "UPDATE ResourceMovement SET actual_return = %s, return_condition = %s "
            "WHERE movement_id = %s",
            (returned_at, return_condition, movement_id),
        )
        # A damaged item must not become issuable again just because it came back.
        new_status = return_condition if return_condition in BAD_CONDITIONS else "Returned"
        cur.execute(
            "UPDATE Resource SET status = %s, resource_condition = %s WHERE resource_id = %s",
            (new_status, return_condition, movement["resource_id"]),
        )
        return new_status


def open_movements():
    """Items that are out now (Lab 10A Q11, with names)."""
    with transaction() as cur:
        cur.execute(
            """
            SELECT rm.movement_id, r.resource_name, r.resource_type, per.full_name AS issued_to,
                   rm.issue_datetime, rm.expected_return
            FROM ResourceMovement rm
            JOIN Resource r ON r.resource_id = rm.resource_id
            JOIN Person per ON per.person_id = rm.person_id
            WHERE rm.actual_return IS NULL
            ORDER BY rm.expected_return
            """
        )
        return cur.fetchall()


def overdue_returns():
    """Lab 10A Q19: issued, past the expected return, not yet returned."""
    with transaction() as cur:
        cur.execute(
            """
            SELECT rm.movement_id, r.resource_name, r.resource_type, per.full_name,
                   per.phone, rm.issue_datetime, rm.expected_return,
                   CURRENT_DATE - rm.expected_return::date AS days_overdue
            FROM ResourceMovement rm
            JOIN Resource r ON r.resource_id = rm.resource_id
            JOIN Person per ON per.person_id = rm.person_id
            WHERE rm.actual_return IS NULL AND rm.expected_return < CURRENT_TIMESTAMP
            ORDER BY days_overdue DESC
            """
        )
        return cur.fetchall()
