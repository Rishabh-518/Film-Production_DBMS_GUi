"""Lab 11 screenshots: add, update and delete a Resource, and a delete the foreign key blocks.
Run from production_app on a fresh film_demo:  .venv/Scripts/python.exe tools/shots_lab11.py
It adds and deletes its own test item, so film_demo is unchanged afterwards.
"""
import subprocess
import sys
import time
import urllib.request

import shots_final as f
import take_screenshots as t
from playwright.sync_api import sync_playwright

t.PORT = 8631
t.URL = f"http://localhost:{t.PORT}"
NAME = "Lab11 Demo Spotlight"


def catalogue(page, search):
    t.go(page, "Catalogue")
    t.fill(page, "Search by name", search)


def add(page):
    catalogue(page, "Lab11")
    t.tab(page, "Add resource")
    t.fill(page, "Name", NAME)
    t.fill(page, "Type (for example Light, Camera)", "Light")
    t.press(page, "Add")
    f.save(page, "L11_01_resource_added")


def update(page):
    catalogue(page, "Lab11")
    t.tab(page, "Edit or delete")
    f.pick_by_keyboard(page, "Resource", NAME)
    t.fill(page, "Name", NAME + " (new bulb)")
    t.press(page, "Save changes")
    f.save(page, "L11_02_resource_updated")


def delete(page):
    catalogue(page, "Lab11")
    t.tab(page, "Edit or delete")
    f.pick_by_keyboard(page, "Resource", NAME)
    t.press(page, "Delete resource")
    f.save(page, "L11_03_resource_deleted")


def delete_blocked(page):
    used = t.query(
        "SELECT r.resource_name FROM Resource r JOIN ResourceMovement m USING (resource_id) "
        "ORDER BY r.resource_id LIMIT 1"
    )[0]["resource_name"]
    catalogue(page, used)
    t.tab(page, "Edit or delete")
    f.pick_by_keyboard(page, "Resource", used)
    t.press(page, "Delete resource")
    f.save(page, "L11_04_delete_blocked_by_foreign_key")


def main():
    server = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", str(t.PORT),
         "--server.headless", "true", "--browser.gatherUsageStats", "false"],
        cwd=t.APP_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    try:
        for _ in range(60):
            try:
                if urllib.request.urlopen(f"{t.URL}/_stcore/health").read() == b"ok":
                    break
            except OSError:
                time.sleep(1)
        with sync_playwright() as pw:
            f.browser = t.Browser(pw)
            for name, steps in (("add", add), ("update", update), ("delete", delete),
                                ("blocked", delete_blocked)):
                f.run(name, "resource", steps)
    finally:
        server.terminate()


main()
