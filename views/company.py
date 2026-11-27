from datetime import date

import pandas as pd
import streamlit as st

from redline import db, preinvest, rules, summary, ui

ui.page_header("Company Profile")
ui.show_notice()

try:
    holdings = db.holdings(candidates=True)
    all_criteria = db.criteria()
    active = [c for c in all_criteria if c["active"]]
    scores = rules.index_scores(db.scores())
    findings = db.findings()
except db.DataError as e:
    st.error(str(e))
    st.stop()

if not holdings or not all_criteria:
    with st.container(border=True, key="panel-company"):
        st.write("An investment universe and at least one criterion are required.")
        target = "views/universe.py" if not holdings else "views/criteria.py"
        st.page_link(target, label="Add companies" if not holdings else "Add criteria", icon=":material/arrow_forward:")
    st.stop()

by_id = {h["id"]: h for h in holdings}
if st.session_state.get(ui.COMPANY_KEY) not in by_id:
    st.session_state.pop(ui.COMPANY_KEY, None)
with st.container(border=True, key="panel-select"):
    holding = by_id[st.selectbox("Company", list(by_id), key=ui.COMPANY_KEY,
                                 format_func=lambda i: by_id[i]["name"] + {"prospect": " (prospect)", "candidate": " (pre-investment)"}.get(
                                     by_id[i]["type"], ""))]
# Every criterion with results for this company, including inactive ones used only in Holding or Pre-investment
# Screening ("screened on demand"), first; then active criteria without results.
with_results = {c for (h, c) in scores if h == holding["id"]} | {f["criterion_id"] for f in findings if f["holding_id"] == holding["id"]}
shown = [c for c in all_criteria if c["id"] in with_results] + [c for c in active if c["id"] not in with_results]


def label(c) -> str:
    return c["label"] if c["active"] else f"{c['label']} (screened on demand)"


# Overall status: active criteria, as on Overview; pre-investment companies use the criteria they were screened for.
basis = [c for c in shown if c["id"] in with_results] if holding["type"] == "candidate" else active
result = rules.evaluate_holding(holding, shown, scores)
overall = rules.evaluate_holding(holding, basis, scores)["state"] if basis else "na"

with st.container(border=True, key="panel-status"):
    st.subheader("Status by Criterion", anchor=False)
    ui.status_badge(overall)
    st.caption("Overall status across the criteria screened." if holding["type"] == "candidate"
               else "Overall status across active criteria. Criteria screened on demand do not affect it.")
    st.dataframe(
        ui.status_style(pd.DataFrame([
            {"Criterion": label(r["criterion"]), "Status": rules.LABELS[r["state"]], "Reason": ", ".join(r["reasons"]),
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
            crit = next(c for c in all_criteria if c["id"] == finding["criterion_id"])
            db.refresh_summaries([(by_id[finding["holding_id"]], crit)])
            ui.set_notice("Finding dismissed.")
            st.rerun()


# Missing or outdated summaries of this company are generated once when its profile opens.
stale = [c for c in shown if summary.needed(scores.get((holding["id"], c["id"])), c)
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
    for c in shown:
        st.markdown(f"**{ui.md_escape(label(c))}**")
        score = scores.get((holding["id"], c["id"])) or {}
        state = rules.evaluate(score, c)["state"]
        ui.status_badge(state)
        pair = [f for f in findings if f["holding_id"] == holding["id"] and f["criterion_id"] == c["id"]]
        if state in ("breach", "watch"):
            if summary.is_current(score, pair, c):
                st.text(score["summary"])
                if score.get("summary_date"):
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


def save_note() -> None:
    text = st.session_state.get(f"note-{holding['id']}", "").strip()
    if not text:
        return
    try:
        db.add_note(holding["id"], text)
    except db.DataError as e:
        st.session_state["_note_error"] = str(e)
        return
    st.session_state[f"note-{holding['id']}"] = ""
    ui.set_notice("Note saved.")


def save_decision() -> None:
    label = st.session_state.get(f"decision-{holding['id']}")
    decision = next(k for k, v in preinvest.DECISIONS.items() if v == label)
    try:
        db.save_holdings([preinvest.decision_change(holding, decision)])
    except db.DataError as e:
        st.session_state["_note_error"] = str(e)
        return
    ui.set_notice("Decision saved.")


def _edit_note(note_id) -> None:
    st.session_state["note-editing"] = note_id
    st.session_state.pop("note-deleting", None)


def _save_edit(note_id) -> None:
    text = st.session_state.get(f"note-edit-{note_id}", "").strip()
    if not text:
        st.session_state["_note_error"] = "A note cannot be empty."
        return
    try:
        db.update_note(note_id, text)
    except db.DataError as e:
        st.session_state["_note_error"] = str(e)
        return
    st.session_state.pop("note-editing", None)
    ui.set_notice("Note updated.")


def _delete_note(note_id) -> None:
    if st.session_state.get("note-deleting") != note_id:      # first click asks for confirmation
        st.session_state["note-deleting"] = note_id
        return
    try:
        db.delete_note(note_id)
    except db.DataError as e:
        st.session_state["_note_error"] = str(e)
        return
    st.session_state.pop("note-deleting", None)
    ui.set_notice("Note deleted.")


def _cancel() -> None:
    st.session_state.pop("note-editing", None)
    st.session_state.pop("note-deleting", None)


def note_row(n) -> None:
    edited = f" \u00b7 edited {n['updated_at'][:10]}" if n.get("updated_at") else ""
    read_only = db.is_read_only()
    with st.container(key=f"note-{n['id']}"):
        if st.session_state.get("note-editing") == n["id"]:
            st.text_area("Edit note", value=n["text"], key=f"note-edit-{n['id']}", max_chars=1000, label_visibility="collapsed")
            with st.container(horizontal=True):
                st.button("Save", key=f"note-save-{n['id']}", type="primary", on_click=_save_edit, args=(n["id"],))
                st.button("Cancel", key=f"note-cancel-{n['id']}", on_click=_cancel)
            return
        st.caption((n.get("created_at") or "")[:10] + edited)
        st.text(n["text"])
        if read_only:
            return
        with st.container(horizontal=True):
            st.button("Edit", key=f"note-e-{n['id']}", type="tertiary", on_click=_edit_note, args=(n["id"],))
            confirming = st.session_state.get("note-deleting") == n["id"]
            st.button("Confirm delete" if confirming else "Delete", key=f"note-d-{n['id']}", type="tertiary",
                      on_click=_delete_note, args=(n["id"],))
            if confirming:
                st.button("Cancel", key=f"note-dc-{n['id']}", type="tertiary", on_click=_cancel)


if holding.get("pre_investment") or holding["type"] in ("candidate", "prospect"):
    try:
        mine_notes = sorted((n for n in db.notes() if n["holding_id"] == holding["id"]),
                            key=lambda n: n.get("created_at") or "", reverse=True)
    except db.DataError as e:
        st.error(str(e))
        mine_notes = []
    with st.container(border=True, key="panel-notes"):
        st.subheader("Investment Notes", anchor=False)
        if "_note_error" in st.session_state:
            st.error(st.session_state.pop("_note_error"))
        if holding.get("pre_investment") or holding["type"] == "candidate":
            current = holding.get("decision") or ("prospect" if holding["type"] == "prospect" else "review")
            st.session_state[f"decision-{holding['id']}"] = preinvest.DECISIONS[current]
            st.selectbox("Decision", list(preinvest.DECISIONS.values()), key=f"decision-{holding['id']}",
                         on_change=save_decision, disabled=db.is_read_only(),
                         help="Added as prospect puts the company in the investment universe; the other decisions keep it out.")
        st.text_area("New note", key=f"note-{holding['id']}", max_chars=1000, placeholder="For example: Revisit in Q1.",
                     disabled=db.is_read_only())
        st.button("Save note", on_click=save_note, disabled=db.is_read_only())
        for n in mine_notes:
            note_row(n)


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
    criteria = {c["id"]: c for c in shown}
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
