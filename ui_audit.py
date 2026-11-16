import streamlit as st

import audit
from access import ADMIN, RuleError
from ui_common import show_table


def show_audit(production, account, classes):
    st.title("Audit history")
    production_id = production["production_id"] if production else None
    if ADMIN in classes:
        everything = st.checkbox("All productions", value=production is None, key="audit_all")
        production_id = None if everything else production_id
    try:
        sections = audit.audit_sections(production_id, classes, account["person_id"])
    except RuleError as err:
        st.error(str(err))
        return
    st.caption("Showing all productions." if production_id is None else f"Production: {production['title']}")
    for title, rows in sections:
        st.subheader(title)
        show_table(rows, title.lower().replace(" ", "_"), f"audit_{title}")
