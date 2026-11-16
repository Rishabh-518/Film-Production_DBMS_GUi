from datetime import date

import streamlit as st

import team
from access import can
from records import list_people
from ui_common import attempt, lookup, pick, show_table


def show_team(production, account, classes):
    st.title("Team and tasks")
    production_id = production["production_id"]
    departments_tab, roles_tab, tasks_tab = st.tabs(["Departments", "Role assignments", "Tasks"])
    with departments_tab:
        show_departments(production_id, classes)
    with roles_tab:
        show_roles(production_id, account, classes)
    with tasks_tab:
        show_tasks(production_id, account, classes)


def show_departments(production_id, classes):
    departments = team.list_departments(production_id)
    show_table(departments, "departments", "departments")
    if not can(classes, "manage_departments"):
        return
    with st.form("add_department", clear_on_submit=True):
        name = st.text_input("Department name")
        description = st.text_area("Description")
        if st.form_submit_button("Add department"):
            attempt(team.add_department, production_id, name, classes, description,
                    done="Department added (rows affected: {result})")
    department = pick("Department to delete", departments, "dept_pick",
                      lambda d: d["department_name"])
    if department is not None and st.button("Delete department", key="delete_dept"):
        attempt(team.delete_department, production_id, department["department_id"], classes,
                done="Department deleted (rows affected: {result})")


def show_roles(production_id, account, classes):
    assignments = team.list_assignments(production_id)
    show_table(assignments, "role_assignments", "roles")
    if not can(classes, "manage_assignments"):
        return
    people = list_people()
    person_names, person_ids = lookup(people, "person_id", "full_name")
    departments = team.departments_for(production_id, classes, account["person_id"])
    if not can(classes, "manage_departments") and not departments:
        st.info("You are not assigned to a department here, so you cannot manage role assignments.")
        return
    if not team.sees_all_departments(classes):
        st.caption("As a Department Head you can manage assignments of your own department only.")
    dept_names, dept_ids = lookup(departments, "department_id", "department_name", include_none=True)
    with st.form("add_assignment", clear_on_submit=True):
        person_id = st.selectbox("Person", person_ids, format_func=person_names.get)
        role_name = st.text_input("Role name", help="Existing roles: " + ", ".join(team.role_names()))
        department_id = st.selectbox("Department", dept_ids, format_func=lambda d: dept_names.get(d, "(none)"))
        start = st.date_input("Start", date.today(), key="role_start")
        end = st.date_input("End", date.today(), key="role_end")
        if st.form_submit_button("Assign role"):
            attempt(team.add_assignment, production_id, person_id, role_name, department_id,
                    start, end, classes, account["person_id"],
                    done="Role assigned (rows affected: {result})")
    chosen = pick("Assignment to remove", assignments, "assign_pick",
                  lambda a: f"{a['full_name']} - {a['role_name']}")
    if chosen is not None and st.button("Remove assignment", key="remove_assignment"):
        attempt(team.remove_assignment, production_id, chosen["assignment_id"], classes,
                account["person_id"],
                done="Assignment removed (rows affected: {result})")


def show_tasks(production_id, account, classes):
    manage = can(classes, "manage_tasks")
    own_only = not manage
    status = st.selectbox("Status", ["All", *team.TASK_STATUSES], key="task_filter")
    overdue = st.checkbox("Overdue only", key="task_overdue")
    person_filter = account["person_id"] if own_only else None
    tasks = team.list_tasks(production_id, status, person_filter, overdue)
    show_table(tasks, "tasks", "tasks")

    task = pick("Task", tasks, "task_pick", lambda t: f"#{t['task_id']} {t['title']} ({t['status']})")
    if task is not None:
        new_status = st.selectbox("New status", team.TASK_STATUSES, key="task_new_status")
        if st.button("Change status", key="task_status_button"):
            attempt(team.set_task_status, production_id, task["task_id"], new_status, classes,
                    account["person_id"], done="Task status changed (rows affected: {result})")
        if manage:
            people = list_people()
            names, ids = lookup(people, "person_id", "full_name")
            assignee = st.selectbox("Assign to", ids, format_func=names.get, key="task_assignee")
            if st.button("Assign task", key="task_assign_button"):
                attempt(team.assign_task, production_id, task["task_id"], assignee, classes,
                        account["person_id"],
                        done="Task assigned (rows affected: {result})")
    if manage:
        departments = team.departments_for(production_id, classes, account["person_id"])
        dept_names, dept_ids = lookup(departments, "department_id", "department_name",
                                      include_none=team.sees_all_departments(classes))
        people = list_people()
        names, ids = lookup(people, "person_id", "full_name", include_none=True)
        with st.form("add_task", clear_on_submit=True):
            title = st.text_input("Title")
            department_id = st.selectbox("Department", dept_ids, format_func=lambda d: dept_names.get(d, "(none)"))
            person_id = st.selectbox("Responsible", ids, format_func=lambda p: names.get(p, "(nobody yet)"))
            due = st.date_input("Due date", date.today())
            priority = st.selectbox("Priority", team.PRIORITIES, index=1)
            if st.form_submit_button("Add task"):
                attempt(team.add_task, production_id, title, department_id, person_id, due,
                        priority, classes, account["person_id"], done="Task added (rows affected: {result})")


def show_documents(production, classes):
    st.title("Documents")
    production_id = production["production_id"]
    status = st.selectbox("Approval status", ["All", *team.DOCUMENT_STATUSES], key="doc_filter")
    documents = team.list_documents(production_id, status)
    show_table(documents, "documents", "documents")
    if can(classes, "manage_documents"):
        with st.form("add_document", clear_on_submit=True):
            title = st.text_input("Title")
            doc_type = st.selectbox("Type", team.DOCUMENT_TYPES)
            link = st.text_input("Storage link")
            version = st.number_input("Version", min_value=1, value=1)
            if st.form_submit_button("Add document (starts as Pending)"):
                attempt(team.add_document, production_id, title, doc_type, link, classes, int(version),
                        done="Document added (rows affected: {result})")
    if can(classes, "approve_document"):
        document = pick("Document to review", documents, "doc_pick",
                        lambda d: f"#{d['doc_id']} {d['title']} v{d['version_no']} ({d['approval_status']})")
        if document is not None:
            approve, reject = st.columns(2)
            if approve.button("Approve", key="approve_document"):
                attempt(team.decide_document, production_id, document["doc_id"], "Approved",
                        classes, done="Document approved (rows affected: {result})")
            if reject.button("Reject", key="reject_document"):
                attempt(team.decide_document, production_id, document["doc_id"], "Rejected",
                        classes, done="Document rejected (rows affected: {result})")
