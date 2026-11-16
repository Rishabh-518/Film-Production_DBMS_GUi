from psycopg2.errors import ForeignKeyViolation

from access import RuleError, require
from db import transaction

# SRS 5.3: the only values the database accepts for Resource.status.
STATUSES = ["Available", "Reserved", "Issued", "Returned", "Damaged", "Under Repair"]
CONDITIONS = ["Good", "Fair", "Damaged", "Under Repair"]


def resource_types():
    with transaction() as cur:
        cur.execute(
            "SELECT DISTINCT resource_type FROM Resource "
            "WHERE resource_type IS NOT NULL ORDER BY resource_type"
        )
        return [row["resource_type"] for row in cur.fetchall()]


def list_resources(search="", resource_type="All", status="All", condition="All"):
    with transaction() as cur:
        cur.execute(
            """
            SELECT resource_id, resource_name, resource_type, resource_condition, status
            FROM Resource
            WHERE resource_name ILIKE %s
              AND (%s = 'All' OR resource_type = %s)
              AND (%s = 'All' OR status = %s)
              AND (%s = 'All' OR resource_condition = %s)
            ORDER BY resource_type, resource_name
            """,
            (f"%{search.strip()}%", resource_type, resource_type, status, status,
             condition, condition),
        )
        return cur.fetchall()


def add_resource(name, resource_type, condition, status, classes):
    """Return the number of rows inserted."""
    require(classes, "manage_resources")
    if not name.strip():
        raise RuleError("A resource needs a name.")
    with transaction() as cur:
        cur.execute(
            """
            INSERT INTO Resource (resource_id, resource_name, resource_type,
                                  resource_condition, status)
            SELECT COALESCE(MAX(resource_id), 0) + 1, %s, %s, %s, %s FROM Resource
            """,
            (name.strip(), resource_type.strip(), condition, status),
        )
        return cur.rowcount


def update_resource(resource_id, name, resource_type, condition, status, classes):
    require(classes, "manage_resources")
    if not name.strip():
        raise RuleError("A resource needs a name.")
    with transaction() as cur:
        cur.execute(
            """
            UPDATE Resource
            SET resource_name = %s, resource_type = %s, resource_condition = %s, status = %s
            WHERE resource_id = %s
            """,
            (name.strip(), resource_type.strip(), condition, status, resource_id),
        )
        return cur.rowcount


def delete_resource(resource_id, classes):
    require(classes, "manage_resources")
    try:
        with transaction() as cur:
            cur.execute("DELETE FROM Resource WHERE resource_id = %s", (resource_id,))
            return cur.rowcount
    except ForeignKeyViolation:
        raise RuleError(
            "This item has reservations or movements, so it can't be deleted. "
            "Set its status to Damaged or Under Repair instead."
        ) from None
