-- The SRS keeps sign-in outside the production database, so accounts get their
-- own schema and the 17 production tables stay unchanged.
CREATE SCHEMA IF NOT EXISTS auth;

CREATE TABLE IF NOT EXISTS auth.account (
    account_id     SERIAL PRIMARY KEY,
    email          VARCHAR(255) NOT NULL UNIQUE,
    password_hash  VARCHAR(60) NOT NULL,
    person_id      INT UNIQUE REFERENCES Person(person_id),
    is_admin       BOOLEAN NOT NULL DEFAULT FALSE,
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT chk_account_email_lowercase CHECK (email = lower(email)),
    CONSTRAINT chk_account_owner CHECK (is_admin OR person_id IS NOT NULL)
);

-- Resource Coordinator, Finance and Viewer work across productions, so they
-- are a property of the account and not of one RoleAssignment row.
ALTER TABLE auth.account ADD COLUMN IF NOT EXISTS account_class VARCHAR(50);
ALTER TABLE auth.account DROP CONSTRAINT IF EXISTS chk_account_class;
ALTER TABLE auth.account ADD CONSTRAINT chk_account_class
    CHECK (account_class IN ('Resource Coordinator', 'Finance', 'Viewer'));
