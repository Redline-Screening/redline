from datetime import date

import pandas as pd
import streamlit as st

from redline import db, rules, ui

ui.page_header("Risk Assessment", "Exposure and likelihood by company and criterion.")
ui.show_notice()

try:
    holdings = db.holdings()
    active = [c for c in db.criteria() if c["active"]]
    scores = rules.index_scores(db.scores())
except db.DataError as e:
    st.error(str(e))
    st.stop()

if not holdings or not active:
    ui.empty_panel("risk", "An investment universe and at least one active criterion are required.")
    st.stop()

with st.container(border=True, key="panel-company"):
    by_id = {h["id"]: h for h in holdings}
    holding = by_id[st.selectbox("Company", list(by_id), format_func=lambda i: by_id[i]["name"])]
    result = rules.evaluate_holding(holding, active, scores)
    st.dataframe(
        ui.status_style(pd.DataFrame([
            {"Criterion": r["criterion"]["label"], "Status": rules.LABELS[r["state"]],
             "Revenue %": (r["score"] or {}).get("exposure"), "Limit %": r["criterion"]["threshold"],
             "Likelihood": (r["score"] or {}).get("likelihood"),
             "Controversy": (rules.controversy_level(r["score"]) or "").capitalize(),
             "Source": (r["score"] or {}).get("source"), "Date": (r["score"] or {}).get("exposure_date")}
            for r in result["results"]
        ]).astype({"Revenue %": float, "Limit %": float, "Likelihood": float})),
        hide_index=True, placeholder="",
        column_config={
            "Revenue %": st.column_config.NumberColumn(format="%.1f"),
            "Limit %": st.column_config.NumberColumn(format="%.1f"),
            "Likelihood": st.column_config.NumberColumn(format="%.0f"),
        },
    )


@st.dialog("Delete assessment")
def confirm_delete(holding_id: str, criterion_id: str) -> None:
    st.write("All figures and controversies for this company and criterion will be deleted permanently.")
    if st.button("Delete", type="primary"):
        try:
            db.delete_score(holding_id, criterion_id)
        except db.DataError as e:
            st.error(str(e))
        else:
            ui.set_notice("Assessment deleted.")
            st.rerun()


with st.container(border=True, key="panel-analyst"):
    st.subheader("Analyst Assessment", anchor=False)
    criteria = {c["id"]: c for c in active}
    cid = st.selectbox("Criterion", list(criteria), format_func=lambda i: criteria[i]["label"])
    score = scores.get((holding["id"], cid)) or {}
    if score.get("exposure_kind") == "provider":
        st.warning("Saving replaces the provider figure with an analyst figure.")
    with st.form(f"analyst-{holding['id']}-{cid}", border=False):
        a, b = st.columns(2)
        number = lambda v: None if v is None else float(v)  # noqa: E731
        exposure = a.number_input("Revenue exposure %", 0.0, 100.0, number(score.get("exposure")), 0.1)
        likelihood = b.number_input("Likelihood of increase (0–100)", 0.0, 100.0, number(score.get("likelihood")), 1.0)
        note = st.text_area("Note", value=score.get("rationale") or "", max_chars=1000)
        submitted = st.form_submit_button("Save assessment", type="primary")
    if submitted:
        if exposure is None:
            st.error("Enter a revenue exposure.")
        else:
            try:
                db.save_score({
                    "holding_id": holding["id"], "criterion_id": cid, "exposure": exposure,
                    "exposure_kind": "analyst", "source": "Analyst", "basis": None,
                    "exposure_date": date.today().isoformat(), "likelihood": likelihood,
                    "confidence": None, "rationale": note.strip() or None, "signals": [],
                })
            except db.DataError as e:
                st.error(str(e))
            else:
                ui.set_notice("Assessment saved.")
                st.rerun()
    if score and st.button("Delete assessment"):
        confirm_delete(holding["id"], cid)
