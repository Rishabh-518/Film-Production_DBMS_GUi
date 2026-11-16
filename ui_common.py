"""Small helpers shared by the screens. The screens hold no SQL."""
from datetime import datetime

import psycopg2
import streamlit as st

from access import ClashError, RuleError
from reports import to_csv


def show_flash():
    message = st.session_state.pop("flash", None)
    if message:
        st.success(message)


def show_clashes(clashes):
    st.warning("These bookings overlap. Tick the confirm box and save again to keep going anyway.")
    st.dataframe(clashes, hide_index=True)


def attempt(action, *args, done="Saved ({result})", **kwargs):
    """Run a write function. Show rule and database errors instead of crashing.

    On success the page reloads with a message built from `done`.
    """
    try:
        result = action(*args, **kwargs)
    except ClashError as err:
        show_clashes(err.clashes)
        return None
    except RuleError as err:
        st.error(str(err))
        return None
    except psycopg2.Error as err:
        st.error(f"The database refused this change: {err.diag.message_primary or err}")
        return None
    st.session_state.flash = done(result) if callable(done) else done.format(result=result)
    st.rerun()


def show_table(rows, name, key, column_config=None):
    if not rows:
        st.info("Nothing to show.")
        return
    st.dataframe(rows, hide_index=True, key=f"table_{key}", column_config=column_config)
    st.download_button(
        "Download CSV", to_csv(rows), file_name=f"{name}.csv", mime="text/csv", key=f"csv_{key}"
    )


def pick(label, rows, key, describe):
    """Choose one row from a list. Returns the row, or None when the list is empty."""
    if not rows:
        st.info("Nothing to choose from yet.")
        return None
    index = st.selectbox(
        label, range(len(rows)), format_func=lambda i: describe(rows[i]), key=key
    )
    return rows[index]


def pick_datetime(label, default, key):
    day_column, time_column = st.columns(2)
    day = day_column.date_input(f"{label} date", default.date(), key=f"{key}_date")
    clock = time_column.time_input(f"{label} time", default.time(), key=f"{key}_time")
    return datetime.combine(day, clock)


def lookup(rows, id_column, name_column, include_none=False):
    """Turn rows into ({id: name}, ids) for selectboxes."""
    names = {row[id_column]: row[name_column] for row in rows}
    ids = ([None] if include_none else []) + list(names)
    return names, ids
