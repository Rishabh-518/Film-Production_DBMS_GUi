"""Create the accounts table and the demo logins. Running it again resets them."""
import re
from pathlib import Path

from auth import CAST_CREW, ROLE_TO_USER_CLASS, hash_password
from db import SETTINGS, transaction

DOMAIN = "silverreelstudios.com"
ADMIN_LOGIN = f"it.admin@{DOMAIN}"
ADMIN_PASSWORD = "Admin@Silver2026"
# One demo login per class, each for a person whose roles ALL map to that class.
# Stage Management gets two (the director and the stage manager).
PERSON_CLASSES = ["Producer", "Stage Management", "Stage Management", "Department Head",
                  "Finance", CAST_CREW]
# Middle word of each password: <FirstName>@<Word>2026.
PASSWORD_WORD = {
    "Producer": "Producer",
    "Stage Management": "Stage",
    "Department Head": "Dept",
    "Finance": "Finance",
    CAST_CREW: "Cast",
    "Resource Coordinator": "Store",
    "Viewer": "Viewer",
}
ACTIVE_STATUSES = ["Pre-production", "Rehearsal", "Shooting"]
# These work across productions, so they are stored on the account itself.
ACCOUNT_CLASSES = ["Resource Coordinator", "Viewer"]


def login_for(full_name):
    """"Neel Nair" -> neel.nair@silverreelstudios.com"""
    return ".".join(re.sub(r"[^a-z]", "", part) for part in full_name.lower().split()) + "@" + DOMAIN


def password_for(full_name, user_class):
    return f"{full_name.split()[0]}@{PASSWORD_WORD[user_class]}2026"


def save_account(cur, email, password, person_id=None, is_admin=False, account_class=None):
    cur.execute(
        """
        INSERT INTO auth.account (email, password_hash, person_id, is_admin, account_class)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (email, hash_password(password), person_id, is_admin, account_class),
    )


def person_of_class(cur, user_class, taken_ids):
    """The person on the most active productions (counted up to 4) whose roles are all one class."""
    cur.execute(
        """
        SELECT p.person_id, p.full_name, ARRAY_AGG(DISTINCT ra.role_name) AS roles,
               COUNT(DISTINCT ra.production_id) FILTER (WHERE pr.status = ANY(%s)) AS active
        FROM Person p
        JOIN RoleAssignment ra ON ra.person_id = p.person_id
        JOIN Production pr ON pr.production_id = ra.production_id
        WHERE p.person_id <> ALL(%s)
        GROUP BY p.person_id, p.full_name
        """,
        (ACTIVE_STATUSES, taken_ids),
    )
    fits = [row for row in cur.fetchall()
            if {ROLE_TO_USER_CLASS.get(role, CAST_CREW) for role in row["roles"]} == {user_class}]
    fits.sort(key=lambda row: (-min(row["active"], 4), row["person_id"]))
    return fits[0] if fits else None


def set_up_accounts():
    """Return [(login, password, who)] for every demo account."""
    logins = [(ADMIN_LOGIN, ADMIN_PASSWORD, "Administrator")]
    taken_ids = []
    with transaction() as cur:
        cur.execute(Path(__file__).with_name("auth_schema.sql").read_text())
        cur.execute("DELETE FROM auth.account")
        save_account(cur, ADMIN_LOGIN, ADMIN_PASSWORD, is_admin=True)
        for user_class in PERSON_CLASSES:
            person = person_of_class(cur, user_class, taken_ids)
            if person is None:
                print(f"No person has only {user_class} roles, skipping.")
                continue
            login, password = login_for(person["full_name"]), password_for(person["full_name"], user_class)
            save_account(cur, login, password, person["person_id"])
            taken_ids.append(person["person_id"])
            logins.append((login, password, f"{person['full_name']} ({user_class})"))
        for account_class in ACCOUNT_CLASSES:
            cur.execute(
                "SELECT person_id, full_name FROM Person WHERE person_id <> ALL(%s) "
                "ORDER BY (person_id IN (SELECT person_id FROM RoleAssignment)), person_id LIMIT 1",
                (taken_ids,),
            )
            person = cur.fetchone()
            login, password = login_for(person["full_name"]), password_for(person["full_name"], account_class)
            save_account(cur, login, password, person["person_id"], account_class=account_class)
            taken_ids.append(person["person_id"])
            logins.append((login, password, f"{person['full_name']} ({account_class})"))
    return logins


def demo_logins():
    """[(login, password)] for the demo accounts already in the database (used by the tests)."""
    with transaction() as cur:
        cur.execute(
            """
            SELECT a.email, a.is_admin, a.account_class, p.full_name,
                   ARRAY_AGG(DISTINCT ra.role_name) FILTER (WHERE ra.role_name IS NOT NULL) AS roles
            FROM auth.account a
            LEFT JOIN Person p ON p.person_id = a.person_id
            LEFT JOIN RoleAssignment ra ON ra.person_id = a.person_id
            WHERE a.email LIKE %s
            GROUP BY a.account_id, a.email, a.is_admin, a.account_class, p.full_name
            ORDER BY a.account_id
            """,
            (f"%@{DOMAIN}",),
        )
        rows = cur.fetchall()
    result = []
    for row in rows:
        if row["is_admin"]:
            result.append((row["email"], ADMIN_PASSWORD))
            continue
        user_class = row["account_class"] or ROLE_TO_USER_CLASS.get(row["roles"][0], CAST_CREW)
        result.append((row["email"], password_for(row["full_name"], user_class)))
    return result


if __name__ == "__main__":
    print("Database:", SETTINGS["dbname"])
    for login, password, who in set_up_accounts():
        print(f"{login:<36} {password:<20} {who}")
