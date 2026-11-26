import pandas as pd
import streamlit as st

from redline import db, rules, ui

try:
    workspace = db.workspace()
    holdings = db.holdings()
    criteria = db.criteria()
    scores = rules.index_scores(db.scores())
    alerts = db.alerts()
except db.DataError as e:
    ui.page_header("Overview", "Exclusion status of the fund.")
    st.error(str(e))
    st.stop()

ui.page_header("Overview", "Exclusion status of the fund.")
ui.show_notice()


@st.dialog("Fund name")
def rename() -> None:
    name = st.text_input("Name", value=workspace.get("name") or "", max_chars=80)
    if st.button("Save", type="primary"):
        try:
            db.save_workspace({"name": name.strip() or None})
        except db.DataError as e:
            st.error(str(e))
        else:
            st.rerun()


with st.container(horizontal=True, vertical_alignment="center"):
    st.text(workspace.get("name") or "Unnamed fund")
    if st.button("Edit name", type="tertiary"):
        rename()

steps = ui.setup_steps(holdings, criteria, workspace)
if not all(s["done"] for s in steps):
    ui.setup_progress(steps)
if not (steps[0]["done"] and steps[1]["done"]):
    st.stop()

data = rules.overview(holdings, criteria, scores)
summary = data["summary"]
open_alerts = [a for a in alerts if a["status"] in ("new", "escalated")]
a, b, c, d = st.columns(4)
a.metric("Weight in breach", f"{summary['breach']['weight']:.2f}%", border=True,
         help=f"Holdings in breach: {summary['breach']['count']}")
b.metric("Weight on watch", f"{summary['watch']['weight']:.2f}%", border=True,
         help=f"Holdings on watch: {summary['watch']['count']}")
c.metric("Open alerts", len(open_alerts), border=True,
         help=f"High severity: {sum(x['severity'] == 'high' for x in open_alerts)}")
d.metric("Fully screened", f"{data['complete']} of {data['held']}", border=True,
         help="Holdings screened against every active criterion.")

with st.container(border=True, key="panel-flagged"):
    st.subheader("Breaches and Watch List", anchor=False)
    if data["flagged"]:
        st.dataframe(
            ui.status_style(pd.DataFrame([
                {"Company": r["holding"]["name"], "Weight %": r["holding"]["weight"],
                 "Criterion": r["criterion"]["label"], "Status": rules.LABELS[r["state"]],
                 "Reason": ", ".join(r["reasons"]), "Revenue %": r["score"].get("exposure") if rules.uses_revenue(r["criterion"]) else None,
                 "Limit %": r["criterion"]["threshold"], "Likelihood": r["score"].get("likelihood"),
                 "Controversy": (rules.controversy_level(r["score"]) or "").capitalize(),
                 "Source": rules.revenue_source(r["score"]) if rules.uses_revenue(r["criterion"]) else None}
                for r in data["flagged"]
            ]).astype({"Weight %": float, "Revenue %": float, "Limit %": float, "Likelihood": float})),
            hide_index=True, placeholder="",
            column_config={
                "Weight %": st.column_config.NumberColumn(format="%.2f"),
                "Revenue %": st.column_config.NumberColumn(format="%.1f"),
                "Limit %": st.column_config.NumberColumn(format="%.1f"),
                "Likelihood": st.column_config.NumberColumn(format="%.0f"),
            },
        )
    elif data["complete"] == data["held"] and data["held"]:
        st.write("No holding is in breach or on watch.")
    else:
        st.write("No breach or watch status recorded. Screening is not complete.")

with st.container(border=True, key="panel-by-criterion"):
    st.subheader("Fund Weight in Breach by Criterion", anchor=False)
    st.dataframe(
        pd.DataFrame([
            {"Criterion": r["criterion"]["label"], "Limit %": r["criterion"]["threshold"],
             "Weight in breach %": float(r["weight"]), "In breach": r["breach"], "On watch": r["watch"],
             "Not screened": r["na"]}
            for r in data["by_criterion"]
        ]).astype({"Limit %": float}),
        hide_index=True, placeholder="",
        column_config={
            "Limit %": st.column_config.NumberColumn(format="%.1f"),
            "Weight in breach %": st.column_config.ProgressColumn(
                format="%.2f", min_value=0, max_value=100, color="#A63D34"),
        },
    )
