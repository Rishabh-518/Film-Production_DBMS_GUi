-- Film and Theatre Production Database - Lab 10A SQL Queries (PostgreSQL)
-- Group 23: Rishabh Patel (202503041), Dev Barot (202503063)
-- Runs on the Lab 9 schema (team_23_ddl.sql) and data (team_23_data.sql).
-- Q1-Q12 are simple (single table, no join).
-- Q13-Q30 are complex (multiple joins, sub-queries, CTEs, window
-- functions, a stored function and a trigger).
-- Each query names the SRS requirement it supports.


-- =====================================================================
-- PART A: SIMPLE QUERIES
-- =====================================================================

-- Q1. List all productions that are plays, earliest start date first.
-- SRS: store production title, type, planned dates and status.
SELECT production_id, title, start_date, end_date, status
FROM Production
WHERE production_type = 'Play'
ORDER BY start_date;

-- Q2. Show the productions that are currently in shooting or rehearsal.
-- SRS: store production status.
SELECT production_id, title, production_type, status
FROM Production
WHERE status IN ('Shooting', 'Rehearsal')
ORDER BY status, title;

-- Q3. Find resources that are available and in good condition, so they
-- can be reserved for an event.
-- SRS: maintain a resource catalogue; prevent unavailable resources.
SELECT resource_id, resource_name, resource_type
FROM Resource
WHERE status = 'Available' AND resource_condition = 'Good'
ORDER BY resource_type, resource_name;

-- Q4. How many productions are there in each status?
-- SRS: role-based dashboards and common reports.
SELECT status, COUNT(*) AS productions
FROM Production
GROUP BY status
ORDER BY productions DESC;

-- Q5. List venues that can hold at least 300 people, largest first.
-- SRS: store event venue.
SELECT venue_id, venue_name, address, capacity
FROM Venue
WHERE capacity >= 300
ORDER BY capacity DESC;

-- Q6. How many resources of each type are in the catalogue?
-- SRS: resource catalogue for props, costumes, equipment and vehicles.
SELECT resource_type, COUNT(*) AS total_items
FROM Resource
GROUP BY resource_type
ORDER BY total_items DESC;

-- Q7. List high-priority tasks that are not finished yet, by due date.
-- SRS: store tasks with responsible person, due date, priority, status.
SELECT task_id, title, due_date, status
FROM Task
WHERE priority = 'High' AND status <> 'Done'
ORDER BY due_date;

-- Q8. Which documents are still waiting for approval?
-- SRS: store document details, versions and approval status.
SELECT doc_id, title, doc_type, version_no
FROM Document
WHERE approval_status = 'Pending'
ORDER BY doc_type, title;

-- Q9. For each expense approval status, show the number of expenses and
-- the total, average and largest amount.
-- SRS: record the approval status of expenses.
SELECT approval_status,
       COUNT(*)              AS expenses,
       SUM(amount)           AS total_amount,
       ROUND(AVG(amount), 2) AS average_amount,
       MAX(amount)           AS largest_amount
FROM Expense
GROUP BY approval_status
ORDER BY total_amount DESC;

-- Q10. List the events in 2026 that are still only scheduled (not yet
-- confirmed), in date order.
-- SRS: store event type, start and end date-time and status.
SELECT event_id, event_type, start_datetime, end_datetime
FROM ProductionEvent
WHERE status = 'Scheduled' AND EXTRACT(YEAR FROM start_datetime) = 2026
ORDER BY start_datetime;

-- Q11. Which issued items have not been returned yet?
-- SRS: record issue, expected return and actual return.
SELECT movement_id, resource_id, person_id, issue_datetime, expected_return
FROM ResourceMovement
WHERE actual_return IS NULL
ORDER BY expected_return;

-- Q12. List productions that run for more than 90 days, with their
-- length in days, longest first.
-- SRS: store planned dates of a production.
SELECT title, start_date, end_date, (end_date - start_date) AS duration_days
FROM Production
WHERE (end_date - start_date) > 90
ORDER BY duration_days DESC;


-- =====================================================================
-- PART B: COMPLEX QUERIES
-- =====================================================================

-- Q13. Generate the call sheet for the event with the most participants:
-- production, venue, latest call-sheet revision and reporting time, and
-- every participant with their role in that production.
-- SRS: generate a call sheet from schedule and assignment records.
SELECT pe.event_id, p.title AS production, pe.event_type, v.venue_name,
       cs.revision_no, cs.call_date, cs.reporting_time,
       per.full_name, ra.role_name, ep.participation_status
FROM ProductionEvent pe
JOIN Production p          ON p.production_id = pe.production_id
LEFT JOIN Venue v          ON v.venue_id = pe.venue_id
LEFT JOIN CallSheet cs     ON cs.event_id = pe.event_id
                          AND cs.revision_no = (SELECT MAX(c2.revision_no)
                                                FROM CallSheet c2
                                                WHERE c2.event_id = pe.event_id)
JOIN EventParticipation ep ON ep.event_id = pe.event_id
JOIN Person per            ON per.person_id = ep.person_id
LEFT JOIN RoleAssignment ra ON ra.person_id = per.person_id
                           AND ra.production_id = pe.production_id
WHERE pe.event_id = (SELECT event_id
                     FROM EventParticipation
                     GROUP BY event_id
                     ORDER BY COUNT(*) DESC, event_id
                     LIMIT 1)
ORDER BY per.full_name;

-- Q14. For every approved budget, show planned, committed and actual
-- (approved) spending, and how much of the plan is left.
-- SRS: show planned, committed and actual totals and their difference.
SELECT p.title, b.version_no,
       SUM(bl.planned_amount)                              AS planned,
       SUM(bl.committed_amount)                            AS committed,
       COALESCE(SUM(ex.actual), 0)                         AS actual,
       SUM(bl.planned_amount) - COALESCE(SUM(ex.actual), 0) AS remaining
FROM Production p
JOIN Budget b      ON b.production_id = p.production_id
JOIN BudgetLine bl ON bl.budget_id = b.budget_id
LEFT JOIN (SELECT line_id, SUM(amount) AS actual
           FROM Expense
           WHERE approval_status = 'Approved'
           GROUP BY line_id) ex ON ex.line_id = bl.line_id
WHERE b.status = 'Approved'
GROUP BY p.production_id, p.title, b.version_no
ORDER BY remaining;

-- Q15. Find budget lines where the money spent (approved and pending
-- expenses) is more than the amount committed.
-- SRS: record committed amounts and actual expenses separately.
SELECT p.title, d.department_name, bl.category, bl.committed_amount,
       SUM(e.amount) AS spent,
       SUM(e.amount) - bl.committed_amount AS over_by
FROM BudgetLine bl
JOIN Budget b         ON b.budget_id = bl.budget_id
JOIN Production p     ON p.production_id = b.production_id
LEFT JOIN Department d ON d.department_id = bl.department_id
JOIN Expense e        ON e.line_id = bl.line_id
WHERE e.approval_status <> 'Rejected'
GROUP BY bl.line_id, p.title, d.department_name, bl.category, bl.committed_amount
HAVING SUM(e.amount) > bl.committed_amount
ORDER BY over_by DESC;

-- Q16. Detect resource clashes: the same resource reserved (not
-- cancelled) for two events whose times overlap.
-- SRS: warn before confirming overlapping resource reservations.
SELECT r.resource_name,
       e1.event_id AS event_a, e1.start_datetime AS a_start, e1.end_datetime AS a_end,
       e2.event_id AS event_b, e2.start_datetime AS b_start, e2.end_datetime AS b_end
FROM EventResourceReservation r1
JOIN EventResourceReservation r2 ON r2.resource_id = r1.resource_id
                                AND r2.event_id > r1.event_id
JOIN ProductionEvent e1 ON e1.event_id = r1.event_id
JOIN ProductionEvent e2 ON e2.event_id = r2.event_id
JOIN Resource r         ON r.resource_id = r1.resource_id
WHERE r1.reservation_status <> 'Cancelled'
  AND r2.reservation_status <> 'Cancelled'
  AND e1.start_datetime < e2.end_datetime
  AND e2.start_datetime < e1.end_datetime;

-- Q17. Which people work on more than one production, and in which ones?
-- SRS: assign a person to one or more roles for a production.
SELECT per.full_name, per.email,
       COUNT(DISTINCT ra.production_id) AS productions,
       STRING_AGG(DISTINCT p.title, ', ') AS production_titles
FROM Person per
JOIN RoleAssignment ra ON ra.person_id = per.person_id
JOIN Production p      ON p.production_id = ra.production_id
GROUP BY per.person_id, per.full_name, per.email
HAVING COUNT(DISTINCT ra.production_id) > 1
ORDER BY productions DESC, per.full_name;

-- Q18. List active productions that have no events scheduled at all.
-- SRS: create rehearsals, shoots, meetings and performances as events.
SELECT p.production_id, p.title, p.status
FROM Production p
WHERE p.status NOT IN ('Completed', 'Archived')
  AND NOT EXISTS (SELECT 1
                  FROM ProductionEvent pe
                  WHERE pe.production_id = p.production_id)
ORDER BY p.title;

-- Q19. Which issued items are overdue (past the expected return date and
-- not returned)? Show who has them and how to contact them.
-- SRS: record the person receiving the item and the expected return.
SELECT r.resource_name, r.resource_type, per.full_name, per.phone,
       rm.issue_datetime, rm.expected_return,
       CURRENT_DATE - rm.expected_return::date AS days_overdue
FROM ResourceMovement rm
JOIN Resource r  ON r.resource_id = rm.resource_id
JOIN Person per  ON per.person_id = rm.person_id
WHERE rm.actual_return IS NULL
  AND rm.expected_return < CURRENT_TIMESTAMP
ORDER BY days_overdue DESC;

-- Q20. Show the directors and producers of each production.
-- SRS: the responsible producer is recorded as a role assignment.
SELECT p.title,
       STRING_AGG(per.full_name || ' (' || ra.role_name || ')', ', '
                  ORDER BY ra.role_name, per.full_name) AS leadership
FROM Production p
JOIN RoleAssignment ra ON ra.production_id = p.production_id
JOIN Person per        ON per.person_id = ra.person_id
WHERE ra.role_name IN ('Director', 'Producer')
GROUP BY p.production_id, p.title
ORDER BY p.title;

-- Q21. For the latest issued call sheet of each event, list the
-- participants who have not acknowledged it yet.
-- SRS: record call-sheet acknowledgement by each recipient.
WITH latest_sheet AS (
    SELECT DISTINCT ON (event_id) sheet_id, event_id, revision_no
    FROM CallSheet
    WHERE status = 'Issued'
    ORDER BY event_id, revision_no DESC
)
SELECT ls.event_id, ls.sheet_id, ls.revision_no,
       per.full_name, per.phone, ep.participation_status
FROM latest_sheet ls
JOIN EventParticipation ep ON ep.event_id = ls.event_id
JOIN Person per            ON per.person_id = ep.person_id
WHERE ep.participation_status IN ('Assigned', 'Present')
  AND NOT EXISTS (SELECT 1
                  FROM CallSheetAcknowledgement a
                  WHERE a.sheet_id = ls.sheet_id
                    AND a.person_id = ep.person_id)
ORDER BY ls.event_id, per.full_name;

-- Q22. In each production, which department has the largest planned
-- budget? (window function RANK)
-- SRS: budget lines for departments and categories.
SELECT title, department_name, planned
FROM (SELECT p.title, d.department_name,
             SUM(bl.planned_amount) AS planned,
             RANK() OVER (PARTITION BY p.production_id
                          ORDER BY SUM(bl.planned_amount) DESC) AS rnk
      FROM BudgetLine bl
      JOIN Department d ON d.department_id = bl.department_id
      JOIN Production p ON p.production_id = d.production_id
      GROUP BY p.production_id, p.title, d.department_id, d.department_name) ranked
WHERE rnk = 1
ORDER BY planned DESC;

-- Q23. List overdue tasks (past due date and not done) with production,
-- department and the responsible person.
-- SRS: store tasks with responsible person, due date, priority, status.
SELECT p.title AS production, d.department_name, t.title AS task,
       t.priority, t.due_date, t.status,
       COALESCE(per.full_name, 'Unassigned') AS responsible
FROM Task t
JOIN Production p      ON p.production_id = t.production_id
LEFT JOIN Department d ON d.department_id = t.department_id
LEFT JOIN Person per   ON per.person_id = t.person_id
WHERE t.due_date < CURRENT_DATE
  AND t.status <> 'Done'
ORDER BY t.due_date;

-- Q24. Which venues are used by more than one production, and by which?
-- SRS: store the venue of each event.
SELECT v.venue_name, v.capacity,
       COUNT(DISTINCT pe.production_id) AS productions,
       STRING_AGG(DISTINCT p.title, ', ') AS production_titles
FROM Venue v
JOIN ProductionEvent pe ON pe.venue_id = v.venue_id
JOIN Production p       ON p.production_id = pe.production_id
GROUP BY v.venue_id, v.venue_name, v.capacity
HAVING COUNT(DISTINCT pe.production_id) > 1
ORDER BY productions DESC;

-- Q25. Find people paid more than the average rate for their role
-- (correlated sub-query).
-- SRS: assign a person to roles for a production.
SELECT per.full_name, ra.role_name, p.title, ra.payment_rate,
       ROUND((SELECT AVG(r2.payment_rate)
              FROM RoleAssignment r2
              WHERE r2.role_name = ra.role_name), 2) AS role_average
FROM RoleAssignment ra
JOIN Person per   ON per.person_id = ra.person_id
JOIN Production p ON p.production_id = ra.production_id
WHERE ra.payment_rate > (SELECT AVG(r2.payment_rate)
                         FROM RoleAssignment r2
                         WHERE r2.role_name = ra.role_name)
ORDER BY ra.role_name, ra.payment_rate DESC;

-- Q26. Total approved spending per production type and year.
-- SRS: role-based dashboards and common reports.
SELECT p.production_type,
       EXTRACT(YEAR FROM e.expense_date) AS expense_year,
       COUNT(*)      AS expenses,
       SUM(e.amount) AS total_spent
FROM Expense e
JOIN BudgetLine bl ON bl.line_id = e.line_id
JOIN Budget b      ON b.budget_id = bl.budget_id
JOIN Production p  ON p.production_id = b.production_id
WHERE e.approval_status = 'Approved'
GROUP BY p.production_type, EXTRACT(YEAR FROM e.expense_date)
ORDER BY p.production_type, expense_year;

-- Q27. Top 10 most used resources: number of active reservations, number
-- of times issued and how often they came back damaged (CTEs).
-- SRS: record resource reservations, issue and return condition.
WITH reservations AS (
    SELECT resource_id, COUNT(*) AS reserved
    FROM EventResourceReservation
    WHERE reservation_status <> 'Cancelled'
    GROUP BY resource_id
),
movements AS (
    SELECT resource_id, COUNT(*) AS issued,
           COUNT(*) FILTER (WHERE return_condition = 'Damaged') AS damaged_returns
    FROM ResourceMovement
    GROUP BY resource_id
)
SELECT r.resource_name, r.resource_type,
       COALESCE(res.reserved, 0)        AS times_reserved,
       COALESCE(m.issued, 0)            AS times_issued,
       COALESCE(m.damaged_returns, 0)   AS damaged_returns
FROM Resource r
LEFT JOIN reservations res ON res.resource_id = r.resource_id
LEFT JOIN movements m      ON m.resource_id = r.resource_id
ORDER BY times_reserved DESC, times_issued DESC
LIMIT 10;

-- Q28. For each archived production, show that its history is kept:
-- number of events, documents and the total amount spent.
-- SRS: archive completed productions without deleting their history.
SELECT p.production_id, p.title, p.end_date,
       (SELECT COUNT(*) FROM ProductionEvent pe
        WHERE pe.production_id = p.production_id) AS events,
       (SELECT COUNT(*) FROM Document d
        WHERE d.production_id = p.production_id) AS documents,
       (SELECT COALESCE(SUM(e.amount), 0)
        FROM Expense e
        JOIN BudgetLine bl ON bl.line_id = e.line_id
        JOIN Budget b      ON b.budget_id = bl.budget_id
        WHERE b.production_id = p.production_id) AS total_spent
FROM Production p
WHERE p.status = 'Archived'
ORDER BY p.end_date;

-- Q29. STORED FUNCTION: fn_budget_summary(production_id) returns the
-- planned, committed, actual (approved) and remaining amount for the
-- approved budget of one production. Then use it for every production
-- that is currently shooting.
-- SRS: show planned, committed and actual totals and their difference.
CREATE OR REPLACE FUNCTION fn_budget_summary(p_production_id INT)
RETURNS TABLE (planned NUMERIC, committed NUMERIC, actual NUMERIC, remaining NUMERIC)
LANGUAGE sql AS $$
    WITH lines AS (
        SELECT bl.line_id, bl.planned_amount, bl.committed_amount
        FROM BudgetLine bl
        JOIN Budget b ON b.budget_id = bl.budget_id
        WHERE b.production_id = p_production_id
          AND b.status = 'Approved'
    ),
    spent AS (
        SELECT COALESCE(SUM(e.amount), 0) AS amount
        FROM Expense e
        JOIN lines l ON l.line_id = e.line_id
        WHERE e.approval_status = 'Approved'
    )
    SELECT (SELECT COALESCE(SUM(planned_amount), 0) FROM lines),
           (SELECT COALESCE(SUM(committed_amount), 0) FROM lines),
           (SELECT amount FROM spent),
           (SELECT COALESCE(SUM(planned_amount), 0) FROM lines)
             - (SELECT amount FROM spent);
$$;

SELECT p.production_id, p.title, s.planned, s.committed, s.actual, s.remaining
FROM Production p
CROSS JOIN LATERAL fn_budget_summary(p.production_id) s
WHERE p.status = 'Shooting'
ORDER BY s.remaining;

-- Q30. TRIGGER: stop a reservation from being confirmed when the resource
-- is damaged or under repair. The test INSERT below tries to confirm an
-- under-repair resource for event 1 and is rejected with an error.
-- SRS: prevent unavailable or under-repair resources from being confirmed.
CREATE OR REPLACE FUNCTION trg_check_resource_available()
RETURNS TRIGGER
LANGUAGE plpgsql AS $$
DECLARE
    v_status VARCHAR(50);
BEGIN
    IF NEW.reservation_status = 'Confirmed' THEN
        SELECT status INTO v_status
        FROM Resource
        WHERE resource_id = NEW.resource_id;

        IF v_status IN ('Damaged', 'Under Repair') THEN
            RAISE EXCEPTION 'Resource % is % and cannot be confirmed',
                NEW.resource_id, v_status;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_reservation_resource_check ON EventResourceReservation;
CREATE TRIGGER trg_reservation_resource_check
BEFORE INSERT OR UPDATE ON EventResourceReservation
FOR EACH ROW
EXECUTE FUNCTION trg_check_resource_available();

-- Test: should fail with "Resource ... is Under Repair and cannot be confirmed"
INSERT INTO EventResourceReservation (event_id, resource_id, reserved_at, reservation_status)
SELECT 1, r.resource_id, NOW(), 'Confirmed'
FROM Resource r
WHERE r.status = 'Under Repair'
  AND NOT EXISTS (SELECT 1 FROM EventResourceReservation x
                  WHERE x.event_id = 1 AND x.resource_id = r.resource_id)
LIMIT 1;
