"""Screening: Portfolio Monitoring and Holding Screening. Pre-investment Screening follows."""
from datetime import date

import pandas as pd
import streamlit as st

from redline import auth, db, rules, runner, service, summary, ui
from redline import criteria as criteria_rules
from redline.constants import AI_NOTE, MONITOR_COST, MONITOR_MAX_COMPANIES, TEMPLATES

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
            state.screening_run = runner.new_run(run_now, web=web, estimate=estimate, kind="manual")
            st.rerun()


BADGE = {"breach": "red", "watch": "orange", "clear": "green", "partial": "gray", "na": "gray"}
ORDER = {"breach": 0, "watch": 1}


def retry(run) -> None:
    """Runs the failed checks again. For monitoring this does not count as a new daily run."""
    jobs = [dict(j, retry=False) for j in run["failed_jobs"]]
    state.screening_run = runner.new_run(jobs, web=run["web"], estimate=run["estimate"], kind=run.get("kind", "manual"))
    state.screening_run["recorded"] = True


def company_header(name, items) -> str:
    """Expander label: company, a badge per criterion, and the new and updated findings or the failure."""
    failed = [c for c in items if c["error"]]
    if failed and len(failed) == len(items):
        return f"**{ui.md_escape(name)}** · :red-badge[Check failed] {ui.md_escape(failed[0]['error'])}"
    badges = " ".join(
        f":red-badge[{ui.md_escape(c['criterion'])}: Failed]" if c["error"] else
        f":{BADGE[c['after']]}-badge[{ui.md_escape(c['criterion'])}: {rules.LABELS[c['after']]}]"
        for c in items)
    new = sum(len(c["new"]) for c in items)
    updated = sum(len(c["updated"]) for c in items)
    found = f"{new} new, {updated} updated" if new or updated else "no incidents found"
    return f"**{ui.md_escape(name)}** · {badges} · {found}"


def company_rank(items) -> tuple:
    if all(c["error"] for c in items):
        return (3,)
    best = min(ORDER.get(c["after"], 2) for c in items if not c["error"])
    return (best,)


def results(run) -> None:
    try:
        all_findings = db.findings()
        findings = {f["id"]: f for f in all_findings}
        scores = rules.index_scores(db.scores())
        status = db.monitor_status() if run.get("kind") == "monitor" else db.ai_status()
    except db.DataError as e:
        st.error(str(e))
        return
    checks = run["checks"]
    allowed = int(status["global"]) > 0 and int(status["budget"]) > 0 if run.get("kind") == "monitor" \
        else int(status["remaining"]) > 0
    with st.container(border=True, key="panel-run"):
        st.subheader("Results of This Run", anchor=False)
        line = (f"Checks completed: {run['done']} of {run['total']}. Failed: {len(run['errors'])}. "
                f"New findings: {run['findings']}.")
        if run["errors"]:
            st.warning(line)
        else:
            st.success(line)
        if run["message"]:
            st.info(run["message"])
        if run["left_out"]:
            st.caption(f"Findings left out because their sources did not match or named an outlet without a link: {run['left_out']}.")
        with st.container(horizontal=True):
            if run["jobs"]:
                st.button(f"Resume ({len(run['jobs'])} open)", type="primary", on_click=resume, disabled=not allowed)
            if run["failed_jobs"] and not run["jobs"] and not db.is_read_only():
                st.button(f"Retry failed checks ({len(run['failed_jobs'])})", type="primary", on_click=retry, args=(run,),
                          disabled=not allowed)
            st.button("Clear results", on_click=clear)

        with st.expander("Results table"):
            st.dataframe(
                ui.status_style(pd.DataFrame([
                    {"Company": c["company"], "Criterion": c["criterion"],
                     "Change": "" if c["error"] else f"{rules.LABELS[c['before']]} \u2192 {rules.LABELS[c['after']]}",
                     "Status": "Failed" if c["error"] else rules.LABELS[c["after"]],
                     "Revenue %": c["exposure"], "Revenue source": c["revenue_source"]}
                    for c in checks
                ], columns=["Company", "Criterion", "Change", "Status", "Revenue %", "Revenue source"]).astype({"Revenue %": float})),
                hide_index=True, placeholder="",
                column_config={"Revenue %": st.column_config.NumberColumn(format="%.1f")},
            )
            st.caption("AI results are estimates. Unsourced revenue estimates can cause Watch but not Breach.")

        companies = {}
        for c in checks:
            companies.setdefault(c["company_id"], []).append(c)
        for n, (company_id, items) in enumerate(sorted(companies.items(), key=lambda kv: company_rank(kv[1]))):
            with st.expander(company_header(items[0]["company"], items)):
                for c in items:
                    st.markdown(f"**{ui.md_escape(c['criterion'])}**")
                    if c["error"]:
                        st.caption(f"Check failed: {c['error']}")
                        continue
                    if c["before"] != c["after"]:
                        st.caption(f"{rules.LABELS[c['before']]} \u2192 {rules.LABELS[c['after']]}")
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
                ui.company_link(company_id, f"View all findings for {items[0]['company']}", key=f"view-{n}")
        st.caption("Incident summaries are generated by AI from the linked sources.")


# ---------- Portfolio Monitoring ----------

def save_monitored() -> None:
    try:
        db.set_monitored(state["pm-companies"], [h["id"] for h in holdings])
    except db.DataError as e:
        state["_pm_error"] = str(e)


def save_enabled() -> None:
    try:
        db.save_workspace({"monitor": {**(workspace.get("monitor") or {}), "enabled": state["pm-enabled"]}})
    except db.DataError as e:
        state["_pm_error"] = str(e)


def portfolio_monitoring() -> None:
    try:
        status = db.monitor_status()
        scores = rules.index_scores(db.scores())
    except db.DataError as e:
        st.error(str(e))
        return
    held = [h for h in holdings if h["type"] == "holding"]
    by_id = {h["id"]: h for h in held}
    active = [c for c in criteria if c["active"]]
    with st.container(border=True, key="panel-monitoring"):
        st.subheader("Portfolio Monitoring", anchor=False)
        if "_pm_error" in state:
            st.error(state.pop("_pm_error"))
        state["pm-enabled"] = bool((workspace.get("monitor") or {}).get("enabled"))
        st.toggle("Daily monitoring", key="pm-enabled", on_change=save_enabled, disabled=db.is_read_only())
        state["pm-companies"] = [h["id"] for h in held if h.get("monitored")]
        st.multiselect(f"Companies (at most {MONITOR_MAX_COMPANIES})", list(by_id), key="pm-companies",
                       max_selections=MONITOR_MAX_COMPANIES, on_change=save_monitored, disabled=db.is_read_only(),
                       format_func=lambda i: by_id[i]["name"], placeholder="Select companies")
        chosen = [by_id[i] for i in state["pm-companies"]]
        last = workspace.get("monitor_last_run")
        kind = {"manual": "manual", "automatic": "automatic"}.get(workspace.get("monitor_last_kind"), "")
        a, b, c, d = st.columns(4)
        a.metric("Companies covered", len(chosen), border=True)
        b.metric("Last run", last or "Not yet", border=True, help=f"Run type: {kind}" if kind else None)
        c.metric("Next run", "07:00" if state["pm-enabled"] else "Off", border=True,
                 help="Daily at 07:00 Swiss time. The automatic schedule is activated in a later stage.")
        d.metric("Expected daily cost", f"${len(chosen) * MONITOR_COST:.2f}", border=True,
                 help="Estimate for one check per company covering all active criteria.")
        st.caption("One check per company covering all active criteria, for incidents since the last monitoring check. "
                   "Results appear on Alerts.")
        jobs = runner.monitoring_jobs(chosen, active, scores)[: int(status["global"])]
        if db.is_read_only():
            st.info("AI checks are not available in the demo account.")
        elif status["run_today"]:
            st.info("Run now is available once per day.")
        elif not chosen:
            st.write("Select at least one company.")
        elif not int(status["budget"]):
            st.info(service.BUDGET_MESSAGE)
        elif not jobs:
            st.info(service.LIMIT_MESSAGE)
        else:
            st.write(f"This will run {len(jobs)} {'check' if len(jobs) == 1 else 'checks'}.")
        ready = bool(jobs) and not status["run_today"] and int(status["budget"]) > 0 and not db.is_read_only() and bool(key)
        if st.button("Run now", type="primary", disabled=not ready):
            if not db.start_monitoring_run():
                st.info("Run now is available once per day.")
                return
            state.screening_run = runner.new_run(jobs, web=True, estimate=estimate, kind="monitor")
            st.rerun()


def record_monitoring(run) -> None:
    """Stores the date of a finished manual monitoring run once."""
    if run.get("kind") == "monitor" and run["done"] and not run.get("recorded"):
        run["recorded"] = True
        try:
            db.save_workspace({"monitor_last_run": date.today().isoformat(), "monitor_last_kind": "manual"})
        except db.DataError:
            run["recorded"] = False


SECTIONS = {"monitoring": "Portfolio Monitoring", "holding": "Holding Screening"}

run = state.get("screening_run")
if run and (run["active"] or run["current"]):
    progress()
else:
    if run:
        state.setdefault("screening-section", "monitoring" if run.get("kind") == "monitor" else "holding")
    if state.get("screening-section") not in SECTIONS:
        state["screening-section"] = "holding"
    section = st.segmented_control("Section", list(SECTIONS), format_func=SECTIONS.get, required=True,
                                   key="screening-section", label_visibility="collapsed")
    if section == "monitoring":
        portfolio_monitoring()
    else:
        holding_screening()
    if run and (run.get("kind") == "monitor") == (section == "monitoring"):
        record_monitoring(run)
        results(run)
