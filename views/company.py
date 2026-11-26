from datetime import date

import pandas as pd
import streamlit as st

from redline import db, rules, summary, ui

ui.page_header("Company Profile")
ui.show_notice()

try:
    holdings = db.holdings()
    active = [c for c in db.criteria() if c["active"]]
    scores = rules.index_scores(db.scores())
    findings = db.findings()
except db.DataError as e:
    st.error(str(e))
    st.stop()

if not holdings or not active:
    with st.container(border=True, key="panel-company"):
        st.write("An investment universe and at least one active criterion are required.")
        target = "views/universe.py" if not holdings else "views/criteria.py"
        st.page_link(target, label="Add companies" if not holdings else "Add criteria", icon=":material/arrow_forward:")
    st.stop()

by_id = {h["id"]: h for h in holdings}
if st.session_state.get(ui.COMPANY_KEY) not in by_id:
    st.session_state.pop(ui.COMPANY_KEY, None)
with st.container(border=True, key="panel-select"):
    holding = by_id[st.selectbox("Company", list(by_id), key=ui.COMPANY_KEY,
                                 format_func=lambda i: by_id[i]["name"] + (" (prospect)" if by_id[i]["type"] == "prospect" else ""))]
result = rules.evaluate_holding(holding, active, scores)

with st.container(border=True, key="panel-status"):
    st.subheader("Status by Criterion", anchor=False)
    ui.status_badge(result["state"])
    st.dataframe(
        ui.status_style(pd.DataFrame([
            {"Criterion": r["criterion"]["label"], "Status": rules.LABELS[r["state"]], "Reason": ", ".join(r["reasons"]),
             "Revenue %": (r["score"] or {}).get("exposure") if rules.uses_revenue(r["criterion"]) else None,
             "Limit %": r["criterion"]["threshold"],
             "Revenue source": rules.revenue_source(r["score"]) if rules.uses_revenue(r["criterion"]) else None,
             "Likelihood": (r["score"] or {}).get("likelihood"),
             "Incident level": (rules.controversy_level(r["score"]) or "").capitalize(),
             "Last web check": ((r["score"] or {}).get("controversy") or {}).get("checked")}
            for r in result["results"]
        ]).astype({"Revenue %": float, "Limit %": float, "Likelihood": float})),
        hide_index=True, placeholder="",
        column_config={
            "Revenue %": st.column_config.NumberColumn(format="%.1f"),
            "Limit %": st.column_config.NumberColumn(format="%.1f"),
            "Likelihood": st.column_config.NumberColumn(format="%.0f"),
        },
    )


@st.dialog("Dismiss finding")
def dismiss(finding) -> None:
    st.text(finding["title"])
    st.write("The finding no longer counts towards the status, and its alert is closed.")
    if st.button("Dismiss", type="primary", key="confirm-dismiss"):
        try:
            db.dismiss_finding(finding)
        except db.DataError as e:
            st.error(str(e))
        else:
            crit = next(c for c in active if c["id"] == finding["criterion_id"])
            db.refresh_summaries([(by_id[finding["holding_id"]], crit)])
            ui.set_notice("Finding dismissed.")
            st.rerun()


# Missing or outdated summaries of this company are generated once when its profile opens.
stale = [c for c in active if summary.needed(scores.get((holding["id"], c["id"])), c)
         and not summary.is_current(scores.get((holding["id"], c["id"])),
                                    [f for f in findings if f["holding_id"] == holding["id"] and f["criterion_id"] == c["id"]], c)]
if stale and not db.is_read_only() and not st.session_state.get(f"_summaries-tried-{holding['id']}"):
    st.session_state[f"_summaries-tried-{holding['id']}"] = True
    db.refresh_summaries([(holding, c) for c in stale])
    try:
        scores = rules.index_scores(db.scores())
    except db.DataError as e:
        st.error(str(e))

mine = [f for f in findings if f["holding_id"] == holding["id"] and f["status"] == "open"]
with st.container(border=True, key="panel-findings"):
    st.subheader("Findings", anchor=False)
    for c in active:
        st.markdown(f"**{ui.md_escape(c['label'])}**")
        score = scores.get((holding["id"], c["id"])) or {}
        state = rules.evaluate(score, c)["state"]
        ui.status_badge(state)
        pair = [f for f in findings if f["holding_id"] == holding["id"] and f["criterion_id"] == c["id"]]
        if state in ("breach", "watch"):
            if summary.is_current(score, pair, c):
                st.text(score["summary"])
                st.caption(f"Summary from {score['summary_date']}")
            else:
                st.caption("Summary available after the next check")
        checked = (score.get("controversy") or {}).get("checked")
        st.caption(f"Last web check: {checked}" if checked else "Not checked with web search.")
        if score.get("exposure_sources") and rules.uses_revenue(c):
            ui.incident_card(f"revenue-{holding['id']}-{c['id']}", f"Revenue exposure {score['exposure']}%",
                             [rules.revenue_source(score), score.get("basis")], f"Quote: {score.get('exposure_quote')}",
                             score["exposure_sources"])
        listed = sorted((f for f in mine if f["criterion_id"] == c["id"]),
                        key=lambda f: (-rules.LEVELS.index(f["severity"]), f.get("date") or ""), reverse=False)
        if checked and not listed:
            st.caption("No incidents found.")
        if listed:
            with st.expander(f"Findings ({len(listed)})"):
                for f in listed:
                    ui.finding_card(f, None if db.is_read_only() else lambda f=f: dismiss(f), seen=True)
    st.caption("AI results are estimates. Incident summaries are generated by AI from the linked sources.")


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


with st.expander("Analyst Assessment"):
    criteria = {c["id"]: c for c in active}
    cid = st.selectbox("Criterion", list(criteria), format_func=lambda i: criteria[i]["label"])
    score = scores.get((holding["id"], cid)) or {}
    revenue = rules.uses_revenue(criteria[cid])
    if revenue and score.get("exposure_kind") == "provider":
        st.warning("Saving replaces the provider figure with an analyst figure.")
    with st.form(f"analyst-{holding['id']}-{cid}", border=False):
        a, b = st.columns(2)
        number = lambda v: None if v is None else float(v)  # noqa: E731
        exposure = a.number_input("Revenue exposure %", 0.0, 100.0, number(score.get("exposure")), 0.1) if revenue else None
        likelihood = (b if revenue else a).number_input("Likelihood of increase (0–100)", 0.0, 100.0, number(score.get("likelihood")), 1.0)
        note = st.text_area("Note", value=score.get("rationale") or "", max_chars=1000)
        submitted = st.form_submit_button("Save assessment", type="primary")
    if submitted:
        if revenue and exposure is None:
            st.error("Enter a revenue exposure.")
        elif not revenue and likelihood is None:
            st.error("Enter a likelihood.")
        else:
            record = {"holding_id": holding["id"], "criterion_id": cid, "likelihood": likelihood,
                      "rationale": note.strip() or None}
            if revenue:
                record |= {"exposure": exposure, "exposure_kind": "analyst", "source": "Analyst", "basis": None,
                           "exposure_date": date.today().isoformat(), "confidence": None, "signals": []}
            elif not score:
                record["source"] = "Analyst"
            try:
                db.save_score(record)
            except db.DataError as e:
                st.error(str(e))
            else:
                db.refresh_summaries([(holding, criteria[cid])])
                ui.set_notice("Assessment saved.")
                st.rerun()
    if score and st.button("Delete assessment"):
        confirm_delete(holding["id"], cid)
