"""Screening. Sections: Holding Screening now; Portfolio Monitoring and Pre-investment Screening follow."""
import pandas as pd
import streamlit as st

from redline import auth, db, rules, runner, service, summary, ui
from redline import criteria as criteria_rules
from redline.constants import AI_NOTE, TEMPLATES

ui.page_header("Screening", "Revenue exposure and incident checks.")
st.caption(AI_NOTE)

state = st.session_state

try:
    holdings = db.holdings()
    criteria = db.criteria()
    workspace = db.workspace()
except db.DataError as e:
    st.error(str(e))
    st.stop()

if not holdings or not any(c["active"] for c in criteria) or not workspace.get("mode"):
    ui.setup_progress(ui.setup_steps(holdings, criteria, workspace))
    st.stop()

estimate = workspace["mode"] != "provider"
key = st.secrets.get("ANTHROPIC_API_KEY")


def stop() -> None:
    state.screening_run["active"] = False


def resume() -> None:
    state.screening_run.update(active=True, message=None, failures=0)


def clear() -> None:
    state.pop("screening_run", None)


def check_line(c) -> str:
    if c["error"]:
        return f"{c['company']} / {c['criterion']}: failed"
    count = len(c["new"]) + len(c["updated"])
    found = "no incidents found" if not count else f"{count} {'finding' if count == 1 else 'findings'}"
    return f"{c['company']} / {c['criterion']}: {rules.LABELS[c['after']]}, {found}"


# ---------- progress while a run is active ----------

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
    with st.container(border=True, key="panel-running"):
        st.subheader("Screening in Progress", anchor=False)
        if run["current"]:
            st.text(f"Check {finished + 1} of {run['total']} – {run['current'].replace(' – ', ' / ', 1)}")
        st.progress(finished / run["total"], text=f"{finished} of {run['total']} checks finished")
        for c in run["checks"]:
            st.text(check_line(c))
        if run["active"]:
            st.button("Stop after current check", on_click=stop)
        else:
            st.caption("Stopping after the current check.")


# ---------- Holding Screening ----------

def criterion_options():
    """Active and inactive criteria, then standard exclusions not yet added (added as inactive when used)."""
    options = {c["id"]: c["label"] + ("" if c["active"] else " (inactive)") for c in criteria}
    used = {c.get("key") for c in criteria}
    options |= {f"template:{t['key']}": f"{t['label']} (standard, not added)" for t in TEMPLATES if t["key"] not in used}
    return options


# Widget values are lost while the progress panel replaces the form, so they are kept here.
FORM = ("hs-companies", "hs-criteria", "hs-method", "hs-skip")


def restore_form() -> None:
    for k in FORM:
        if k not in state and f"_{k}" in state:
            state[k] = state[f"_{k}"]


def keep_form() -> None:
    for k in FORM:
        if k in state:
            state[f"_{k}"] = state[k]


def holding_screening() -> None:
    restore_form()
    try:
        scores = rules.index_scores(db.scores())
        status = db.ai_status()
    except db.DataError as e:
        st.error(str(e))
        return
    remaining = int(status["remaining"])
    by_id = {h["id"]: h for h in holdings}
    with st.container(border=True, key="panel-screening"):
        st.subheader("Holding Screening", anchor=False)
        if any(i not in by_id for i in state.get("hs-companies", [])):
            state["hs-companies"] = [i for i in state["hs-companies"] if i in by_id]
        picked = st.multiselect("Companies", list(by_id), placeholder="Select companies", key="hs-companies",
                                format_func=lambda i: by_id[i]["name"] + (" (prospect)" if by_id[i]["type"] == "prospect" else ""))
        companies = [by_id[i] for i in picked]
        options = criterion_options()
        if any(i not in options for i in state.get("hs-criteria", [])):
            state["hs-criteria"] = [i for i in state["hs-criteria"] if i in options]
        if "hs-criteria" not in state:
            state["hs-criteria"] = [c["id"] for c in criteria if c["active"]]
        chosen = st.multiselect("Criteria", list(options), format_func=options.get, key="hs-criteria")
        methods = {"web": "Web search"} | ({"quick": "Quick estimate"} if estimate else {})
        if state.get("hs-method") not in methods:
            state["hs-method"] = "web"
        method = st.segmented_control("Method", list(methods), required=True, format_func=methods.get, key="hs-method")
        web = method == "web"
        st.caption("One check per company and criterion, about 30 to 60 seconds each. Findings are saved with sources." if web else
                   "One check per company. AI estimate of revenue exposure without web search or findings. "
                   "Conduct-based criteria are not covered.")
        state.setdefault("hs-skip", True)
        skip = st.checkbox("Exclude combinations checked in the last 7 days", key="hs-skip") if web else False

        templates = [k.removeprefix("template:") for k in chosen if k.startswith("template:")]
        planned = [c for c in criteria if c["id"] in chosen] + criteria_rules.from_templates(templates, criteria)
        jobs = runner.build_jobs(companies, planned, scores, web=web, skip_days=7 if skip else 0)
        run_now = jobs[:remaining]
        if not companies or not chosen:
            st.write("Select at least one company and one criterion.")
        elif not jobs:
            st.write("No checks to run with this selection.")
        elif db.is_read_only():
            st.info("AI checks are not available in the demo account.")
        elif not remaining:
            st.info(service.BUDGET_MESSAGE if not int(status["budget"]) else service.LIMIT_MESSAGE)
        elif len(jobs) > remaining:
            st.write(f"This selection needs {len(jobs)} checks. {remaining} remaining today: this will run {remaining} checks, "
                     "largest weights first.")
        else:
            st.write(f"This will run {len(jobs)} {'check' if len(jobs) == 1 else 'checks'}. {remaining} remaining today.")
        if templates and jobs:
            st.caption("Standard exclusions not yet added are added as inactive criteria. Their results do not affect the "
                       "status on Overview.")
        if not key and not db.is_read_only():
            st.warning("AI screening is not configured.")
        if st.button("Run screening", type="primary", disabled=not run_now or not key or db.is_read_only()):
            new = [c for c in planned if c["id"] not in {x["id"] for x in criteria}]
            for c in new:
                c["active"] = False
            try:
                db.save_criteria(new)
            except db.DataError as e:
                st.error(str(e))
                return
            keep_form()
            state.screening_run = runner.new_run(run_now, web=web, estimate=estimate)
            st.rerun()


def results(run) -> None:
    try:
        all_findings = db.findings()
        findings = {f["id"]: f for f in all_findings}
        scores = rules.index_scores(db.scores())
        status = db.ai_status()
    except db.DataError as e:
        st.error(str(e))
        return
    checks = run["checks"]
    with st.container(border=True, key="panel-run"):
        st.subheader("Results of This Run", anchor=False)
        st.write(f"Checks completed: {run['done']} of {run['total']}. Failed: {len(run['errors'])}. "
                 f"New findings: {run['findings']}. New alerts: {run['alerts']}.")
        if run["message"]:
            st.info(run["message"])
        if run["left_out"]:
            st.caption(f"Findings left out because their sources did not match or named an outlet without a link: {run['left_out']}.")
        with st.container(horizontal=True):
            if run["jobs"]:
                st.button(f"Resume ({len(run['jobs'])} open)", type="primary", on_click=resume,
                          disabled=int(status["remaining"]) < 1)
            st.button("Clear results", on_click=clear)

        with st.expander("Results", expanded=True):
            st.dataframe(
                ui.status_style(pd.DataFrame([
                    {"Company": c["company"], "Criterion": c["criterion"],
                     "Change": "" if c["error"] else f"{rules.LABELS[c['before']]} → {rules.LABELS[c['after']]}",
                     "Status": "Failed" if c["error"] else rules.LABELS[c["after"]],
                     "Revenue %": c["exposure"], "Revenue source": c["revenue_source"]}
                    for c in checks
                ], columns=["Company", "Criterion", "Change", "Status", "Revenue %", "Revenue source"]).astype({"Revenue %": float})),
                hide_index=True, placeholder="",
                column_config={"Revenue %": st.column_config.NumberColumn(format="%.1f")},
            )
            st.caption("AI results are estimates. Unsourced revenue estimates can cause Watch but not Breach.")

        with st.expander("Findings", expanded=True):
            linked = set()
            for i, c in enumerate(checks):
                st.markdown(f"**{ui.md_escape(c['company'])} / {ui.md_escape(c['criterion'])}**")
                if c["error"]:
                    st.caption(f"Check failed: {c['error']}")
                else:
                    criterion = next((x for x in criteria if x["id"] == c["criterion_id"]), None)
                    score = scores.get((c["company_id"], c["criterion_id"]))
                    pair = [f for f in all_findings if f["holding_id"] == c["company_id"] and f["criterion_id"] == c["criterion_id"]]
                    if criterion and summary.needed(score, criterion):
                        if summary.is_current(score, pair, criterion):
                            st.text(score["summary"])
                        else:
                            st.caption("Summary available after the next check")
                    shown = [(findings[x], "New") for x in c["new"] if x in findings]
                    shown += [(findings[x], "Updated") for x in c["updated"] if x in findings]
                    if not shown:
                        st.caption(f"No incidents found for {c['company']} / {c['criterion']}.")
                    for f, mark in sorted(shown, key=lambda p: (p[1] != "New", -rules.LEVELS.index(p[0]["severity"]))):
                        ui.finding_card(f, mark=mark)
                last = i + 1 == len(checks) or checks[i + 1]["company_id"] != c["company_id"]
                if last and c["company_id"] not in linked:
                    linked.add(c["company_id"])
                    ui.company_link(c["company_id"], f"View all findings for {c['company']}", key=f"view-{i}")
            st.caption("Incident summaries are generated by AI from the linked sources.")


run = state.get("screening_run")
if run and (run["active"] or run["current"]):
    progress()
else:
    holding_screening()
    if run:
        results(run)
