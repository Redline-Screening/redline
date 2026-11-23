from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from redline import db, importers, providers, rules, ui
from redline.constants import MODES, PROVIDERS

SAMPLES = Path(__file__).resolve().parent.parent / "sample"

ui.page_header("Data Sources", "Provider data and AI screening method.")
ui.show_notice()

state = st.session_state
state.setdefault("sources_version", 0)
version = state.sources_version

try:
    workspace = db.workspace()
    holdings = db.holdings()
    criteria = [c for c in db.criteria() if c["active"]]
    scores = rules.index_scores(db.scores())
    alerts = db.alerts()
except db.DataError as e:
    st.error(str(e))
    st.stop()

mode = workspace.get("mode")
loaded = workspace.get("providers") or {}


def finish(message: str, provider_id: str, count: int) -> None:
    db.save_workspace({"providers": {**loaded, provider_id: {"last": date.today().isoformat(), "rows": count}}})
    state.sources_version += 1
    ui.set_notice(message)
    st.rerun()


def read(file):
    return importers.read_table(importers.decode(file.getvalue()))


def figures_panel() -> None:
    provider_id = st.selectbox("Provider", list(PROVIDERS), index=None, format_func=PROVIDERS.get,
                               placeholder="Select a provider")
    st.caption("Required columns: isin, ticker or company; revenue %. Optional: category, flag. "
               "Ranges use their upper bound.")
    file = st.file_uploader("Provider file (CSV)", type=["csv", "txt"], max_upload_size=5, key=f"figures-{version}")
    if file is None:
        st.download_button("Download illustrative file", (SAMPLES / "provider.csv").read_bytes(), "provider.csv", "text/csv")
        return
    try:
        table = read(file)
        names = providers.categories(table)
        if len(names) > 60:
            raise importers.ImportProblem("The file has more than 60 categories.")
        # Conduct-based criteria have no revenue limit.
        eligible = [c for c in criteria if rules.uses_revenue(c)]
        options = [None, *(c["id"] for c in eligible)]
        labels = {None: "Not assigned", **{c["id"]: c["label"] for c in eligible}}
        st.markdown("**Category assignment**")
        chosen = {}
        for i, name in enumerate(names):
            left, right = st.columns([1.2, 1], vertical_alignment="center")
            left.text(name)
            chosen[name] = right.selectbox(
                f"Criterion {i + 1}", options, index=options.index(providers.guess_criterion(name, eligible)),
                format_func=labels.get, label_visibility="collapsed", key=f"category-{version}-{file.file_id}-{i}")
        plan = providers.plan_figures(table, holdings, eligible, chosen, scores,
                                      PROVIDERS.get(provider_id, ""))
    except importers.ImportProblem as e:
        st.error(str(e))
        return
    st.dataframe(
        pd.DataFrame([
            {"Row": r["row"], "Action": r["action"], "Company": r["company"], "Criterion": r["criterion"],
             "Revenue %": r["share"], "Note": r["note"]}
            for r in plan["rows"]
        ]).astype({"Revenue %": float}),
        hide_index=True, placeholder="",
    )
    n, skipped = len(plan["records"]), sum(r["action"] == "Skip" for r in plan["rows"])
    st.caption(f"{n} figures to import, {skipped} rows skipped.")
    if st.button("Import figures", type="primary", disabled=not n or provider_id is None,
                 help="Select a provider first." if provider_id is None else None):
        try:
            db.save_scores(plan["records"])
            finish(f"Provider figures imported: {n}.", provider_id, n)
        except db.DataError as e:
            st.error(str(e))


def incidents_panel() -> None:
    st.caption("Required columns: isin, ticker or company; headline. Optional: date, severity, url, issues, summary.")
    file = st.file_uploader("RepRisk incident file (CSV)", type=["csv", "txt"], max_upload_size=5, key=f"incidents-{version}")
    if file is None:
        st.download_button("Download sample file", (SAMPLES / "incidents.csv").read_bytes(), "incidents.csv", "text/csv")
        return
    try:
        plan = providers.plan_incidents(read(file), holdings, criteria, alerts)
    except importers.ImportProblem as e:
        st.error(str(e))
        return
    st.dataframe(
        pd.DataFrame([
            {"Row": r["row"], "Action": r["action"], "Company": r["company"], "Headline": r["title"], "Note": r["note"]}
            for r in plan["rows"]
        ]),
        hide_index=True,
    )
    n = len(plan["records"])
    st.caption(f"{n} incidents to import, {len(plan['rows']) - n} rows skipped.")
    if st.button("Import incidents", type="primary", disabled=not n):
        try:
            db.add_alerts(plan["records"])
            finish(f"Incidents imported: {n}.", "reprisk", n)
        except db.DataError as e:
            st.error(str(e))


with st.container(border=True, key="panel-mode"):
    st.subheader("Screening Method", anchor=False)
    keys = list(MODES)
    choice = st.radio("Screening method", keys, index=keys.index(mode) if mode in keys else None,
                      format_func=lambda k: MODES[k][0], captions=[MODES[k][1] for k in keys],
                      label_visibility="collapsed")
    if st.button("Save method", type="secondary" if mode else "primary", disabled=choice in (None, mode)):
        try:
            db.save_workspace({"mode": choice})
        except db.DataError as e:
            st.error(str(e))
        else:
            ui.set_notice("Screening method saved.")
            st.rerun()

if mode in ("provider", "both"):
    with st.container(border=True, key="panel-provider"):
        st.subheader("Provider Files", anchor=False)
        if not holdings or not criteria:
            st.write("An investment universe and at least one active criterion are required.")
        else:
            names = {**PROVIDERS, "reprisk": "RepRisk"}
            for key, info in loaded.items():
                if key in names:
                    st.caption(f"{names[key]}: {info.get('rows')} rows loaded on {info.get('last')}.")
            figures_tab, incidents_tab = st.tabs(["Revenue figures", "Incidents"])
            with figures_tab:
                figures_panel()
            with incidents_tab:
                incidents_panel()

if mode:
    ui.next_step("views/screening.py", "Screening")
