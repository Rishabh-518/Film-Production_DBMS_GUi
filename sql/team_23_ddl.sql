-- Film and Theatre Production Database - DDL (PostgreSQL)
-- Group 23: Rishabh Patel (202503041), Dev Barot (202503063)
-- Final schema in BCNF. Tables are created parents first, so every
-- foreign key refers to a table that already exists.

-- 1. Independent tables
CREATE TABLE Production (
    production_id    INT PRIMARY KEY,
    title            VARCHAR(255) NOT NULL,
    production_type  VARCHAR(100),
    start_date       DATE,
    end_date         DATE,
    status           VARCHAR(50),
    CONSTRAINT chk_production_dates CHECK (end_date >= start_date)
);

CREATE TABLE Venue (
    venue_id      INT PRIMARY KEY,
    venue_name    VARCHAR(255) NOT NULL,
    address       TEXT,
    contact_info  VARCHAR(255),
    capacity      INT,
    CONSTRAINT chk_venue_capacity CHECK (capacity > 0)
);

CREATE TABLE Person (
    person_id  INT PRIMARY KEY,
    full_name  VARCHAR(255) NOT NULL,
    email      VARCHAR(255) UNIQUE,
    phone      VARCHAR(50)
);

CREATE TABLE Resource (
    resource_id         INT PRIMARY KEY,
    resource_name       VARCHAR(255) NOT NULL,
    resource_type       VARCHAR(100),
    resource_condition  VARCHAR(255),
    status              VARCHAR(50),
    CONSTRAINT chk_resource_status CHECK (status IN
        ('Available', 'Reserved', 'Issued', 'Returned', 'Damaged', 'Under Repair'))
);

-- 2. Tables that depend on Production
CREATE TABLE Department (
    department_id    INT PRIMARY KEY,
    production_id    INT NOT NULL,
    department_name  VARCHAR(255) NOT NULL,
    description      TEXT,
    FOREIGN KEY (production_id) REFERENCES Production(production_id),
    CONSTRAINT uq_department_name UNIQUE (production_id, department_name),
    CONSTRAINT uq_department_production UNIQUE (department_id, production_id)
);

CREATE TABLE Budget (
    budget_id       INT PRIMARY KEY,
    production_id   INT NOT NULL,
    version_no      INT NOT NULL,
    effective_date  DATE,
    status          VARCHAR(50),
    FOREIGN KEY (production_id) REFERENCES Production(production_id),
    CONSTRAINT uq_budget_version UNIQUE (production_id, version_no),
    CONSTRAINT chk_budget_version CHECK (version_no >= 1)
);

CREATE TABLE Document (
    doc_id           INT PRIMARY KEY,
    production_id    INT NOT NULL,
    title            VARCHAR(255) NOT NULL,
    doc_type         VARCHAR(100),
    storage_link     TEXT,
    version_no       INT,
    approval_status  VARCHAR(50),
    FOREIGN KEY (production_id) REFERENCES Production(production_id),
    CONSTRAINT chk_document_version CHECK (version_no >= 1)
);

CREATE TABLE ProductionEvent (
    event_id        INT PRIMARY KEY,
    production_id   INT NOT NULL,
    venue_id        INT,
    event_type      VARCHAR(100),
    start_datetime  TIMESTAMP,
    end_datetime    TIMESTAMP,
    status          VARCHAR(50),
    hosting_notes   TEXT,
    FOREIGN KEY (production_id) REFERENCES Production(production_id),
    FOREIGN KEY (venue_id) REFERENCES Venue(venue_id),
    CONSTRAINT chk_event_times CHECK (end_datetime > start_datetime)
);

-- 3. Second-level tables
CREATE TABLE BudgetLine (
    line_id           INT PRIMARY KEY,
    budget_id         INT NOT NULL,
    department_id     INT,
    category          VARCHAR(100),
    planned_amount    DECIMAL(15, 2),
    committed_amount  DECIMAL(15, 2),
    FOREIGN KEY (budget_id) REFERENCES Budget(budget_id),
    FOREIGN KEY (department_id) REFERENCES Department(department_id),
    CONSTRAINT uq_budget_line UNIQUE (budget_id, department_id, category),
    CONSTRAINT chk_line_amounts CHECK (planned_amount >= 0 AND committed_amount >= 0)
);

CREATE TABLE RoleAssignment (
    assignment_id  INT PRIMARY KEY,
    production_id  INT NOT NULL,
    department_id  INT,
    person_id      INT NOT NULL,
    role_name      VARCHAR(100) NOT NULL,
    start_date     DATE,
    end_date       DATE,
    payment_rate   DECIMAL(15, 2),
    FOREIGN KEY (production_id) REFERENCES Production(production_id),
    FOREIGN KEY (department_id) REFERENCES Department(department_id),
    FOREIGN KEY (person_id) REFERENCES Person(person_id),
    -- the department, when given, must belong to the same production
    CONSTRAINT fk_assignment_dept_production FOREIGN KEY (department_id, production_id)
        REFERENCES Department(department_id, production_id),
    CONSTRAINT chk_assignment_dates CHECK (end_date >= start_date),
    CONSTRAINT chk_payment_rate CHECK (payment_rate >= 0)
);

CREATE TABLE Task (
    task_id        INT PRIMARY KEY,
    production_id  INT NOT NULL,
    department_id  INT,
    person_id      INT,
    title          VARCHAR(255) NOT NULL,
    due_date       DATE,
    priority       VARCHAR(50),
    status         VARCHAR(50),
    FOREIGN KEY (production_id) REFERENCES Production(production_id),
    FOREIGN KEY (department_id) REFERENCES Department(department_id),
    FOREIGN KEY (person_id) REFERENCES Person(person_id),
    -- the department, when given, must belong to the same production
    CONSTRAINT fk_task_dept_production FOREIGN KEY (department_id, production_id)
        REFERENCES Department(department_id, production_id)
);

CREATE TABLE CallSheet (
    sheet_id        INT PRIMARY KEY,
    event_id        INT NOT NULL,
    call_date       DATE,
    reporting_time  TIME,
    revision_no     INT NOT NULL,
    status          VARCHAR(50),
    FOREIGN KEY (event_id) REFERENCES ProductionEvent(event_id),
    CONSTRAINT uq_callsheet_revision UNIQUE (event_id, revision_no),
    CONSTRAINT chk_revision_no CHECK (revision_no >= 1)
);

CREATE TABLE ResourceMovement (
    movement_id       INT PRIMARY KEY,
    resource_id       INT NOT NULL,
    person_id         INT NOT NULL,
    issue_datetime    TIMESTAMP,
    expected_return   TIMESTAMP,
    actual_return     TIMESTAMP,
    return_condition  VARCHAR(255),
    FOREIGN KEY (resource_id) REFERENCES Resource(resource_id),
    FOREIGN KEY (person_id) REFERENCES Person(person_id),
    CONSTRAINT chk_expected_return CHECK (expected_return >= issue_datetime),
    CONSTRAINT chk_actual_return CHECK (actual_return >= issue_datetime)
);

-- 4. Third-level table
CREATE TABLE Expense (
    expense_id       INT PRIMARY KEY,
    line_id          INT NOT NULL,
    vendor           VARCHAR(255),
    expense_date     DATE,
    amount           DECIMAL(15, 2) NOT NULL,
    approval_status  VARCHAR(50),
    receipt_link     TEXT,
    FOREIGN KEY (line_id) REFERENCES BudgetLine(line_id),
    CONSTRAINT chk_expense_amount CHECK (amount > 0)
);

-- 5. Tables for M:N relationships
CREATE TABLE EventResourceReservation (
    event_id            INT,
    resource_id         INT,
    reserved_at         TIMESTAMP,
    reservation_status  VARCHAR(50),
    PRIMARY KEY (event_id, resource_id),
    FOREIGN KEY (event_id) REFERENCES ProductionEvent(event_id),
    FOREIGN KEY (resource_id) REFERENCES Resource(resource_id)
);

CREATE TABLE EventParticipation (
    event_id              INT,
    person_id             INT,
    participation_status  VARCHAR(50),
    PRIMARY KEY (event_id, person_id),
    FOREIGN KEY (event_id) REFERENCES ProductionEvent(event_id),
    FOREIGN KEY (person_id) REFERENCES Person(person_id)
);

CREATE TABLE CallSheetAcknowledgement (
    sheet_id         INT,
    person_id        INT,
    acknowledged_at  TIMESTAMP,
    PRIMARY KEY (sheet_id, person_id),
    FOREIGN KEY (sheet_id) REFERENCES CallSheet(sheet_id),
    FOREIGN KEY (person_id) REFERENCES Person(person_id)
);
