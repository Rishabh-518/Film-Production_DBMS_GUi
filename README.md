# Film and Theatre Production Database – GUI

MC212 Database Management Systems, Team 23
Rishabh Patel (202503041), Dev Barot (202503063)

A Streamlit web application on a PostgreSQL database (17 tables) for planning film and theatre
productions: schedules with clash checks, call sheets, resources (reserve, issue, return), budgets and
expense approval, documents, people and tasks, and accounts. Each page and each write operation is
limited to the user classes allowed by the SRS access matrix (`access.py`).

## Stack
Python 3.14, psycopg2, Streamlit, bcrypt, PostgreSQL 18.

## Set up
1. Create a PostgreSQL database named `Film production project` and run `sql/team_23_ddl.sql`, then
   `sql/team_23_data.sql`.
2. Create a virtual environment and install the packages:
   ```
   python -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   ```
3. Copy `db_config.example.py` to `db_config.py` and fill in your connection details.
   `db_config.py` is listed in `.gitignore` and is never committed.
4. Build the demo copy of the database (realistic dates and data) and its logins:
   ```
   $env:APP_DBNAME = "film_demo"; .venv\Scripts\python.exe tools\seed_demo.py
   ```
5. Start the app with `run_demo.ps1` and open http://localhost:8501.
   The demo logins are listed in `DEMO_LOGINS.md`.

## Code layout
- `db.py`: connection and the `transaction()` helper (commit on success, rollback on error).
- `access.py`: who may do what (SRS section 9); every write function calls `require()` itself.
- `schedule.py`, `callsheets.py`, `resources.py`, `movements.py`, `budget.py`, `team.py`, `records.py`,
  `accounts.py`, `audit.py`, `reports.py`: database operations, one module per area.
- `ui_*.py`, `app.py`, `navigation.py`: the Streamlit pages.
- `tools/`: demo data, tests (`smoke_test.py`, `test_permissions.py`, `test_dashboards.py`) and the
  screenshot scripts.
- `sql/`: the schema, sample data and the Lab 10A queries.

## Tests
Run on a copy of the database (never the main one):
```
$env:APP_DBNAME = "film_test"; .venv\Scripts\python.exe tools\test_permissions.py
$env:APP_DBNAME = "film_test"; .venv\Scripts\python.exe tools\smoke_test.py
```
