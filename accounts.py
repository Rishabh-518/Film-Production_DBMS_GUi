"""Sign-in accounts: who can log in, their access class, and password resets (Admin only)."""
from psycopg2.errors import CheckViolation, UniqueViolation

from access import RuleError, require
from auth import hash_password
from db import transaction

# Matches chk_account_class in auth_schema.sql. None means the class comes from role assignments.
ACCOUNT_CLASSES = [None, "Resource Coordinator", "Finance", "Viewer"]
MIN_PASSWORD_LENGTH = 6


def list_accounts(classes):
    """Never selects password_hash, so it cannot reach a screen."""
    require(classes, "view_accounts")
    with transaction() as cur:
        cur.execute(
            """
            SELECT a.account_id, a.email, p.full_name, a.is_admin, a.account_class, a.is_active
            FROM auth.account a LEFT JOIN Person p ON p.person_id = a.person_id
            ORDER BY a.email
            """
        )
        return cur.fetchall()


def people_without_account(classes):
    require(classes, "manage_accounts")
    with transaction() as cur:
        cur.execute(
            """
            SELECT person_id, full_name FROM Person
            WHERE person_id NOT IN (SELECT person_id FROM auth.account WHERE person_id IS NOT NULL)
            ORDER BY full_name
            """
        )
        return cur.fetchall()


def check_password(password):
    if len(password) < MIN_PASSWORD_LENGTH:
        raise RuleError(f"The password needs at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password.encode()) > 72:
        raise RuleError("The password is too long (72 bytes at most).")


def create_account(email, password, person_id, is_admin, account_class, classes):
    """Return the new account_id. An account is an admin, or belongs to one existing Person."""
    require(classes, "manage_accounts")
    email = email.strip().lower()
    if "@" not in email:
        raise RuleError("Enter a valid email address.")
    check_password(password)
    if not is_admin and person_id is None:
        raise RuleError("Link the account to a person, or make it an admin account.")
    if is_admin and account_class:
        raise RuleError("An admin account does not take an access class.")
    if account_class not in ACCOUNT_CLASSES:
        raise RuleError("Unknown access class.")
    try:
        with transaction() as cur:
            cur.execute(
                """
                INSERT INTO auth.account (email, password_hash, person_id, is_admin, account_class)
                VALUES (%s, %s, %s, %s, %s) RETURNING account_id
                """,
                (email, hash_password(password), person_id, is_admin, account_class),
            )
            return cur.fetchone()["account_id"]
    except UniqueViolation:
        raise RuleError("That email, or that person, already has an account.") from None
    except CheckViolation:
        raise RuleError("The database refused this account.") from None


def set_account_class(account_id, account_class, classes):
    require(classes, "manage_accounts")
    if account_class not in ACCOUNT_CLASSES:
        raise RuleError("Unknown access class.")
    with transaction() as cur:
        cur.execute(
            "UPDATE auth.account SET account_class = %s WHERE account_id = %s AND NOT is_admin",
            (account_class, account_id),
        )
        if cur.rowcount == 0:
            raise RuleError("That account does not exist, or it is an admin account.")
        return cur.rowcount


def set_active(account_id, active, classes, acting_account_id):
    """Disable keeps the account and its history; it only stops sign-in."""
    require(classes, "manage_accounts")
    if not active and account_id == acting_account_id:
        raise RuleError("You cannot disable your own account.")
    with transaction() as cur:
        cur.execute(
            "UPDATE auth.account SET is_active = %s WHERE account_id = %s", (active, account_id)
        )
        if cur.rowcount == 0:
            raise RuleError("That account does not exist.")
        return cur.rowcount


def reset_password(account_id, new_password, classes):
    require(classes, "manage_accounts")
    check_password(new_password)
    with transaction() as cur:
        cur.execute(
            "UPDATE auth.account SET password_hash = %s WHERE account_id = %s",
            (hash_password(new_password), account_id),
        )
        if cur.rowcount == 0:
            raise RuleError("That account does not exist.")
        return cur.rowcount
