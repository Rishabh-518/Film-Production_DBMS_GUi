import bcrypt

from db import transaction

BCRYPT_MAX_BYTES = 72

# Role names are free text (SRS 5.1), so any role not listed here gets the
# least access: a new crew job needs no code change.
CAST_CREW = "Cast / Crew"
ROLE_TO_USER_CLASS = {
    "Producer": "Producer",
    "Production Manager": "Producer",
    "Director": "Stage Management",
    "Stage Manager": "Stage Management",
    "Assistant Director": "Stage Management",
    "Department Head": "Department Head",
    "Costume Designer": "Department Head",
    "Set Designer": "Department Head",
    "Lighting Designer": "Department Head",
    "Sound Engineer": "Department Head",
    "Resource Coordinator": "Resource Coordinator",
    "Venue Coordinator": "Resource Coordinator",
    "Finance Manager": "Finance",
    "Viewer": "Viewer",
    "Auditor": "Viewer",
}


def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def password_matches(password, stored_hash):
    encoded = password.encode()
    if len(encoded) > BCRYPT_MAX_BYTES:
        return False
    return bcrypt.checkpw(encoded, stored_hash.encode())


def find_account(email):
    with transaction() as cur:
        cur.execute(
            """
            SELECT a.account_id, a.email, a.password_hash, a.person_id,
                   a.is_admin, a.is_active, a.account_class, p.full_name
            FROM auth.account a
            LEFT JOIN Person p ON p.person_id = a.person_id
            WHERE a.email = %s
            """,
            (email.strip().lower(),),
        )
        return cur.fetchone()


def authenticate(email, password):
    """Return the account for valid credentials, otherwise None."""
    account = find_account(email)
    if account is None or not account["is_active"]:
        return None
    if not password_matches(password, account["password_hash"]):
        return None
    del account["password_hash"]
    return account


def user_classes(account, roles):
    """A person can hold several roles in one production, so this returns a set."""
    if account["is_admin"]:
        return {"Admin"}
    if account["account_class"]:
        return {account["account_class"]}
    return {ROLE_TO_USER_CLASS.get(role, CAST_CREW) for role in roles}
