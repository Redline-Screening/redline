import pandas as pd
import streamlit as st

from redline import auth, db, rules, runner, service, ui
from redline.constants import AI_NOTE

ui.page_header("Screening", "Revenue exposure and incident checks.")
st.caption(AI_NOTE)

state = st.session_state

try:
    holdings = db.holdings()
    active = [c for c in db.criteria() if c["active"]]
    workspace = db.workspace()
    scores = rules.index_scores(db.scores())
    findings = db.findings()
    status = db.ai_status()
except db.DataError as e:
    st.error(str(e))
    st.stop()

if not holdings or not active or not workspace.get("mode"):
    ui.setup_progress(ui.setup_steps(holdings, active, workspace))
    st.stop()

estimate = workspace["mode"] != "provider"
remaining = int(status["remaining"])
key = st.secrets.get("ANTHROPIC_API_KEY")


def stop() -> None:
    state.screening_run["active"] = False


def resume() -> None:
    run = state.screening_run
    run.update(active=True, message=None, failures=0)


def close() -> None:
    state.pop("screening_run", None)


@st.fragment(run_every=2)
def progress() -> None:
    run = state.get("screening_run")
    if run is None:
        return
    if run["active"] and not run["current"]:
        try:
            auth.ensure_fresh()
        except auth.SignInError as e:
            run["message"], run["active"] = str(e), False
        else:
            runner.start_next(run, auth.client(), service.claude(key))
    if not run["active"] and not run["current"]:
        st.rerun()
    finished = run["total"] - len(run["jobs"]) - bool(run["current"])
    st.progress(finished / run["total"], text=f"{finished} of {run['total']} checks finished")
    if run["current"]:
        st.text(f"In progress: {run['current']}")
    if run["active"]:
        st.button("Stop after current check", on_click=stop)
    else:
        st.caption("Stopping after the current check.")


def summary(run) -> None:
    st.subheader("Last Screening", anchor=False)
    st.write(f"Checks completed: {run['done']} of {run['total']}. New findings: {run['findings']}. New alerts: {run['alerts']}. "
             f"Failed: {len(run['errors'])}.")
    if run["message"]:
        st.info(run["message"])
    for text in run["errors"]:
        st.text(text)
    with st.container(horizontal=True):
        if run["jobs"]:
            st.button(f"Resume ({len(run['jobs'])} open)", type="primary", on_click=resume, disabled=remaining < 1)
        st.button("Close", on_click=close)


def setup() -> None:
    by_id = {h["id"]: h for h in holdings}
    scope = st.segmented_control("Companies", ["holdings", "selected"], default="holdings", required=True,
                                 format_func={"holdings": "All holdings", "selected": "Selected companies"}.get)
    if scope == "holdings":
        companies = [h for h in holdings if h["type"] == "holding"]
    else:
        chosen = st.multiselect("Selected companies", list(by_id), label_visibility="collapsed",
                                format_func=lambda i: by_id[i]["name"] + (" (prospect)" if by_id[i]["type"] == "prospect" else ""))
        companies = [by_id[i] for i in chosen]
    labels = {c["id"]: c["label"] for c in active}
    picked = st.multiselect("Criteria", list(labels), default=list(labels), format_func=labels.get)
    criteria = [c for c in active if c["id"] in picked]
    methods = {"web": "Web search"} | ({"quick": "Quick estimate"} if estimate else {})
    method = st.segmented_control("Method", list(methods), default="web", required=True, format_func=methods.get)
    web = method == "web"
    if web:
        st.caption("One check per company and criterion, about 30 to 60 seconds each. Findings are saved with sources.")
    else:
        st.caption("One check per company. AI estimate of revenue exposure without web search or findings. "
                   "Conduct-based criteria are not covered.")
    skip = st.checkbox("Exclude combinations checked in the last 7 days", value=True) if web else False

    jobs = runner.build_jobs(companies, criteria, scores, web=web, skip_days=7 if skip else 0)
    run_now = jobs[:remaining]
    if not jobs:
        st.write("No checks to run with this selection.")
    elif not remaining:
        st.info(service.BUDGET_MESSAGE if not int(status["budget"]) else service.LIMIT_MESSAGE)
    elif len(jobs) > remaining:
        st.write(f"This selection needs {len(jobs)} checks. {remaining} remaining today: this will run {remaining} checks, "
                 "largest weights first.")
    else:
        st.write(f"This will run {len(jobs)} {'check' if len(jobs) == 1 else 'checks'}. {remaining} remaining today.")
    if not key:
        st.warning("AI screening is not configured.")
    if st.button("Run screening", type="primary", disabled=not run_now or not key):
        state.screening_run = runner.new_run(run_now, web=web, estimate=estimate)
        st.rerun()


run = state.get("screening_run")
running = bool(run and (run["active"] or run["current"]))
with st.container(border=True, key="panel-screening"):
    if running:
        progress()
    else:
        if run:
            summary(run)
            st.divider()
        st.subheader("New Screening", anchor=False)
        setup()

if not running:
    by_id, labels = {h["id"]: h for h in holdings}, {c["id"]: c for c in active}
    rows = [(by_id[h], labels[c], s) for (h, c), s in scores.items() if h in by_id and c in labels]
    with st.container(border=True, key="panel-results"):
        st.subheader("Results", anchor=False)
        if not rows:
            st.write("No screening has been run.")
        else:
            order = {"breach": 0, "watch": 1}
            table = sorted(((h, c, s, rules.evaluate(s, c)) for h, c, s in rows),
                           key=lambda r: (order.get(r[3]["state"], 2), -(r[0]["weight"] or 0)))
            count = {}
            for f in findings:
                if f["status"] == "open":
                    count[(f["holding_id"], f["criterion_id"])] = count.get((f["holding_id"], f["criterion_id"]), 0) + 1
            st.dataframe(
                ui.status_style(pd.DataFrame([
                    {"Company": h["name"], "Criterion": c["label"], "Status": rules.LABELS[e["state"]],
                     "Reason": ", ".join(e["reasons"]),
                     "Revenue %": s.get("exposure") if rules.uses_revenue(c) else None, "Likelihood": s.get("likelihood"),
                     "Incident level": (rules.controversy_level(s) or "").capitalize(),
                     "Findings": count.get((h["id"], c["id"]), 0), "Revenue source": s.get("source") if rules.uses_revenue(c) else None,
                     "Checked": (s.get("controversy") or {}).get("checked") or s.get("exposure_date")}
                    for h, c, s, e in table
                ]).astype({"Revenue %": float, "Likelihood": float})),
                hide_index=True, placeholder="",
                column_config={"Revenue %": st.column_config.NumberColumn(format="%.1f"),
                               "Likelihood": st.column_config.NumberColumn(format="%.0f")},
            )
            st.caption("AI results are estimates. Incident summaries are generated by AI from the linked sources.")

    with_findings = [h for h in holdings if any(f["holding_id"] == h["id"] for f in findings)]
    if with_findings:
        with st.container(border=True, key="panel-results-findings"):
            st.subheader("Findings", anchor=False)
            names = {h["id"]: h["name"] for h in with_findings}
            selected = st.selectbox("Company", list(names), format_func=names.get, key="findings-company")
            shown = [f for f in findings if f["holding_id"] == selected and f["status"] == "open"]
            for c in active:
                mine = sorted((f for f in shown if f["criterion_id"] == c["id"]),
                              key=lambda f: -rules.LEVELS.index(f["severity"]))
                if mine:
                    st.text(c["label"])
                    for f in mine:
                        ui.finding_card(f)
