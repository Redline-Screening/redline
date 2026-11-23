import pandas as pd
import streamlit as st

from redline import criteria as rules
from redline import db, ui
from redline.constants import CONTROVERSY_LIMITS, TEMPLATES

ui.page_header("Exclusion Criteria", "Revenue limits, controversy levels and watch levels.")
ui.show_notice()

state = st.session_state
state.setdefault("criteria_version", 0)
version = state.criteria_version

try:
    items = db.criteria()
except db.DataError as e:
    st.error(str(e))
    st.stop()


def store(message: str, changed: list[dict], removed: list[str] = ()) -> None:
    try:
        db.save_criteria(changed)
        db.delete_criteria(list(removed))
    except db.DataError as e:
        st.error(str(e))
        return
    state.criteria_version += 1
    ui.set_notice(message)
    st.rerun()


@st.dialog("Remove criteria")
def confirm(changed: list[dict], removed: list[str]) -> None:
    st.write(f"Criteria to remove: {len(removed)}. Their screening results will also be deleted permanently. "
             "To keep the results, clear Active instead.")
    if st.button("Remove", type="primary"):
        store(f"Criteria updated: {len(changed)}. Removed: {len(removed)}.", changed, removed)


def table_panel() -> None:
    frame = pd.DataFrame(items, columns=["id", *rules.FIELDS])
    frame["threshold"] = pd.to_numeric(frame["threshold"]).astype(float)
    frame["watch_at"] = pd.to_numeric(frame["watch_at"]).astype(float)
    frame["keywords"] = [", ".join(c.get("keywords") or []) for c in items]
    frame["description"] = frame["description"].astype("string")
    frame["remove"] = False
    edited = st.data_editor(
        frame,
        hide_index=True,
        placeholder="",
        key=f"criteria-table-{version}",
        column_order=["active", "label", "threshold", "controversy_limit", "watch_at", "remove", "description", "keywords"],
        column_config={
            "active": st.column_config.CheckboxColumn("Active", width="small"),
            "label": st.column_config.TextColumn("Criterion", required=True, width="medium"),
            "threshold": st.column_config.NumberColumn(
                "Revenue limit %", min_value=0, max_value=100, required=True, format="%.1f",
                help="Maximum share of revenue. Any share above the limit is a breach."),
            "controversy_limit": st.column_config.SelectboxColumn(
                "Controversy breach", options=list(CONTROVERSY_LIMITS), format_func=CONTROVERSY_LIMITS.get,
                required=True, help="Controversy level that counts as a breach."),
            "watch_at": st.column_config.NumberColumn(
                "Watch level", min_value=0, max_value=100, required=True, format="%.0f",
                help="Likelihood of rising exposure (0–100) that places a company on watch."),
            "description": st.column_config.TextColumn("Description", width="medium"),
            "keywords": st.column_config.TextColumn("Keywords", width="medium", help="Separated by commas."),
            "remove": st.column_config.CheckboxColumn("Remove", width="small"),
        },
    )
    rows = edited.astype(object).where(edited.notna(), None).to_dict("records")
    try:
        changed, removed = rules.diff_edits(items, rows)
    except rules.CriterionProblem as e:
        st.error(str(e))
        return
    if st.button("Save changes", type="primary", disabled=not (changed or removed)):
        if removed:
            confirm(changed, removed)
        else:
            store(f"Criteria updated: {len(changed)}.", changed)


def template_panel() -> None:
    used = {c.get("key") for c in items}
    open_templates = {t["key"]: t for t in TEMPLATES if t["key"] not in used}
    if not open_templates:
        st.caption("All standard exclusions have been added.")
        return
    keys = st.multiselect("Standard exclusions", list(open_templates),
                          format_func=lambda k: open_templates[k]["label"], key=f"templates-{version}")
    if keys:
        st.dataframe(
            pd.DataFrame([
                {"Criterion": t["label"], "Revenue limit %": t["threshold"],
                 "Controversy breach": CONTROVERSY_LIMITS[t["controversy_limit"]],
                 "Watch level": t["watch_at"], "Description": t["description"]}
                for k, t in open_templates.items() if k in keys
            ]),
            hide_index=True,
        )
    if st.button("Add criteria", type="secondary" if items else "primary", disabled=not keys):
        new = rules.from_templates(keys, items)
        store(f"Criteria added: {len(new)}.", new)


def custom_panel() -> None:
    with st.form(f"custom-{version}", border=False):
        label = st.text_input("Criterion", max_chars=80)
        description = st.text_area("Description", max_chars=500, help="Activities that count towards the criterion.")
        a, b, c = st.columns(3)
        threshold = a.number_input("Revenue limit %", 0.0, 100.0, 0.0, 0.5)
        limit = b.selectbox("Controversy breach", list(CONTROVERSY_LIMITS), index=1, format_func=CONTROVERSY_LIMITS.get)
        watch = c.number_input("Watch level", 0, 100, 50, 5)
        keywords = st.text_input("Keywords", help="Separated by commas. Used to match provider categories and news.")
        if not st.form_submit_button("Add criterion"):
            return
    try:
        new = rules.custom(label, description, threshold, limit, watch, keywords, items)
    except rules.CriterionProblem as e:
        st.error(str(e))
    else:
        store("Criterion added.", [new])


if items:
    active = sum(c["active"] for c in items)
    st.caption(f"Active criteria: {active} of {len(items)}.")
    with st.container(border=True, key="panel-criteria"):
        table_panel()

with st.container(border=True, key="panel-add"):
    template_tab, custom_tab = st.tabs(["Standard exclusions", "Custom criterion"])
    with template_tab:
        template_panel()
    with custom_tab:
        custom_panel()

if items:
    ui.next_step("views/sources.py", "Data Sources")
