"""Renders Home and every visible page for each demo login, headless, with AppTest.

Run from production_app:  .venv/Scripts/python.exe tools/test_dashboards.py [dbname]
The database defaults to film_demo.
"""
import logging
import os
import sys
from pathlib import Path

os.environ["APP_DBNAME"] = sys.argv[1] if len(sys.argv) > 1 else "film_demo"
APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from streamlit.testing.v1 import AppTest  # noqa: E402

import auth  # noqa: E402
import navigation  # noqa: E402
import setup_auth  # noqa: E402
from productions import is_current, productions_visible_to  # noqa: E402

logging.disable(logging.WARNING)
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + (f"  [{detail}]" if detail and not condition else ""))
    if not condition:
        failures.append(name)


def render(account, page, production_id=None):
    app = AppTest.from_file(str(APP_DIR / "app.py"), default_timeout=90)
    app.session_state["account"] = account
    app.session_state["page"] = page
    if production_id is not None:
        app.session_state["production_id"] = production_id
    app.run()
    return app


def problems_of(app):
    problems = [e.value for e in app.exception]
    if not app.title:
        problems.append("no title drawn")
    return "; ".join(problems)[:300]


def home_has_content(app):
    tiles = [m.value for m in app.metric]
    nonzero = any(str(v) not in ("0", "") for v in tiles)
    return nonzero or len(app.dataframe) > 1


def test_login(login, password):
    account = auth.authenticate(login, password)
    check(f"login {login}", account is not None)
    if account is None:
        return
    productions = productions_visible_to(account)
    roles = [r for p in productions for r in p["roles"]]
    top_classes = auth.user_classes(account, roles)

    home = render(account, navigation.HOME)
    check(f"{login}: Home renders", not problems_of(home), problems_of(home))
    check(f"{login}: Home shows something", home_has_content(home))

    for page in navigation.page_names(top_classes, False):
        app = render(account, page)
        check(f"{login}: {page} (no production)", not problems_of(app), problems_of(app))

    current = [p for p in productions if is_current(p)] or productions
    if not current:
        return
    production = current[0]
    classes = auth.user_classes(account, production["roles"])
    for page in navigation.page_names(classes, True):
        if page == navigation.HOME:
            continue
        app = render(account, page, production["production_id"])
        check(f"{login}: {page} in '{production['title']}'", not problems_of(app), problems_of(app))


def main():
    for login, password in setup_auth.demo_logins():
        test_login(login, password)
    print(f"\n{len(failures)} failure(s) on {os.environ['APP_DBNAME']}")
    sys.exit(1 if failures else 0)


main()
