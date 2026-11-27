"""Screening: Portfolio Monitoring and Holding Screening. Pre-investment Screening follows."""
from datetime import date

import pandas as pd
import streamlit as st

from redline import auth, companies as company_list, db, importers, preinvest, rules, runner, service, summary, ui
from redline import criteria as criteria_rules
from redline.constants import AI_NOTE, CONTROVERSY_LIMITS, MONITOR_COST, MONITOR_MAX_COMPANIES, TEMPLATES, TYPES

_SECTION_TITLES = {"monitoring": "Portfolio Monitoring", "holding": "Holding Screening", "pre": "Pre-investment Screening"}
# Screening opens on Portfolio Monitoring unless another section was chosen.
if st.session_state.get("screening-section") not in _SECTION_TITLES:
    st.session_state["screening-section"] = "monitoring"
ui.page_header(_SECTION_TITLES[st.session_state["screening-section"]])

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
FORM = ("hs-companies", "hs-criteria", "hs-method", "hs-skip", "pre-company", "pre-isin", "pre-ticker", "pre-criteria")


def restore_form() -> None:
    for k in FORM:
        if k not in state and f"_{k}" in state:
            state[k] = state[f"_{k}"]


def keep_form() -> None:
    for k in FORM:
        if k in state:
            state[f"_{k}"] = state[k]


def _create_criterion(field: str, text: str, slot: str) -> None:
    """Creates a typed criterion as inactive and puts it in place of the typed text."""
    try:
        new = criteria_rules.custom(state[f"{slot}-type"], company_list.suggest_criterion(text)["label"], "",
                                    None if state[f"{slot}-type"] == "conduct" else 0.0, "high", 50,
                                    state[f"{slot}-keywords"], criteria)
        new["active"] = False
        db.save_criteria([new])
    except (criteria_rules.CriterionProblem, db.DataError) as e:
        state["_criteria_error"] = str(e)
        return
    state[field] = [new["id"] if x == text else x for x in state[field]]
    state["_criteria_notice"] = f"Criterion '{new['label']}' created as inactive."


def criteria_field(field: str):
    """Criteria selection. A name that does not exist yet can be typed and created as an inactive criterion.

    Returns the chosen criteria (planned, including standard exclusions to add) and the typed names not yet created.
    """
    options = criterion_options()
    if field not in state:
        state[field] = [c["id"] for c in criteria if c["active"]]
    chosen = st.multiselect("Criteria", list(options), format_func=lambda x: options.get(x, x), key=field,
                            accept_new_options=True, placeholder="Select or type a criterion",
                            help="Type a name that does not exist yet to create a new criterion.")
    if "_criteria_error" in state:
        st.error(state.pop("_criteria_error"))
    if "_criteria_notice" in state:
        st.caption(state.pop("_criteria_notice"))
    pending = [x for x in chosen if x not in options]
    for n, text in enumerate(pending):
        slot = f"{field}-new-{n}"
        suggestion = company_list.suggest_criterion(text)
        with st.container(border=True, key=f"panel-{slot}"):
            st.markdown(f"**Create criterion '{ui.md_escape(suggestion['label'])}'**")
            a, b = st.columns([1, 2])
            if state.get(f"{slot}-for") != text:      # new suggestion for a new name
                state[f"{slot}-for"], state[f"{slot}-type"] = text, suggestion["type"]
                state[f"{slot}-keywords"] = suggestion["keywords"]
            a.selectbox("Type", list(TYPES), format_func=TYPES.get, key=f"{slot}-type")
            b.text_input("Keywords", key=f"{slot}-keywords", help="Separated by commas.")
            st.caption("Saved as an inactive criterion: it does not affect the status of the portfolio. "
                       + ("Breach level: " + CONTROVERSY_LIMITS["high"] + "." if state[f"{slot}-type"] == "conduct"
                          else "Revenue limit: 0%. Adjust it in Exclusion Criteria."))
            st.button("Create criterion", key=f"{slot}-create", on_click=_create_criterion, args=(field, text, slot),
                      disabled=db.is_read_only())
    known = [x for x in chosen if x in options]
    templates = [k.removeprefix("template:") for k in known if k.startswith("template:")]
    planned = [c for c in criteria if c["id"] in known] + criteria_rules.from_templates(templates, criteria)
    return known, planned, templates, pending


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
        if any(i not in by_id for i in state.get("hs-companies", [])):
            state["hs-companies"] = [i for i in state["hs-companies"] if i in by_id]
        picked = st.multiselect("Companies", list(by_id), placeholder="Select companies", key="hs-companies",
                                format_func=lambda i: by_id[i]["name"] + (" (prospect)" if by_id[i]["type"] == "prospect" else ""))
        companies = [by_id[i] for i in picked]
        chosen, planned, templates, pending = criteria_field("hs-criteria")
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

        jobs = runner.build_jobs(companies, planned, scores, web=web, skip_days=7 if skip else 0)
        run_now = jobs[:remaining] if not pending else []
        if pending:
            st.write("Create or remove the new criterion first.")
        elif not companies or not chosen:
            st.write("Select at least one company and one criterion.")
        elif not jobs:
            st.write("No checks to run with this selection.")
        elif db.is_read_only():
            st.info("AI checks are not available in the demo account.")
        elif not remaining:
            st.info(service.BUDGET_MESSAGE if not int(status["budget"]) else service.limit_message(status))
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
        if run.get("log_errors"):
            st.warning(f"Alert log entries could not be saved for {run['log_errors']} checks. The results themselves are saved.")
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
        if "_pm_error" in state:
            st.error(state.pop("_pm_error"))
        state["pm-enabled"] = bool((workspace.get("monitor") or {}).get("enabled"))
        with st.container(horizontal=True, vertical_alignment="center", key="pm-switch"):
            st.toggle("Daily monitoring", key="pm-enabled", on_change=save_enabled, disabled=db.is_read_only())
            st.html(f'<p class="rl-switch-state">{"On \u2013 next run 07:00" if state["pm-enabled"] else "Off"}</p>')
        state["pm-companies"] = [h["id"] for h in held if h.get("monitored")]
        st.multiselect(f"Companies (at most {MONITOR_MAX_COMPANIES})", list(by_id), key="pm-companies",
                       max_selections=MONITOR_MAX_COMPANIES, on_change=save_monitored, disabled=db.is_read_only(),
                       format_func=lambda i: by_id[i]["name"], placeholder="Select companies")
        chosen = [by_id[i] for i in state["pm-companies"]]
        last = workspace.get("monitor_last_run")
        kind = {"manual": "manual", "automatic": "automatic"}.get(workspace.get("monitor_last_kind"), "")
        a, b, d = st.columns(3)
        a.metric("Companies covered", len(chosen), border=True)
        b.metric("Last run", last or "Not yet", border=True, help=f"Run type: {kind}" if kind else None)
        d.metric("Expected daily cost", f"${len(chosen) * MONITOR_COST:.2f}", border=True,
                 help="Estimate for one check per company covering all active criteria.")
        st.caption("One check per company covering all active criteria, for incidents since the last monitoring check. "
                   "Results appear on Alerts.")
        if workspace.get("monitor_last_kind") == "automatic" and workspace.get("monitor_note"):
            st.caption(f"Last automatic run ({workspace.get('monitor_last_run')}): {workspace['monitor_note']}")
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


# ---------- Pre-investment Screening ----------

def add_as_prospect(company_id: str) -> None:
    try:
        company = next(h for h in db.holdings(candidates=True) if h["id"] == company_id)
        db.save_holdings([preinvest.decision_change(company, "prospect")])
    except (db.DataError, StopIteration):
        state["_pre_error"] = "The company could not be added."
        return
    state["_pre_added"] = company_id


def fill_company(listed) -> None:
    """A suggestion fills ISIN and ticker; free text keeps the fields for manual entry."""
    picked = state.get("pre-company")
    if picked in listed:
        state["pre-isin"], state["pre-ticker"] = listed[picked]["isin"], listed[picked]["ticker"]
    state.pop("pre-figi", None)
    state.pop("pre-figi-name", None)


def pick_figi(results) -> None:
    choice = state.get("pre-figi-pick")
    if choice is not None:
        state["pre-ticker"], state["pre-figi-name"] = results[choice]["ticker"], results[choice]["name"]


def figi_search(text: str) -> None:
    """Free lookup of listed companies outside the bundled list (OpenFIGI: names and tickers, no ISINs)."""
    if state.get("pre-figi-for") != text:
        state["pre-figi-for"], state["pre-figi"] = text, None
        state.pop("pre-figi-name", None)
    if state.get("pre-figi") is None:
        if st.button("Search listed companies", key="pre-figi-search",
                     help="Searches OpenFIGI for listed companies with this name. Free; returns names and tickers."):
            state["pre-figi"] = company_list.openfigi(text)
            st.rerun()
        return
    results = state["pre-figi"]
    if not results:
        st.caption("No listed company found. The name is used as entered.")
        return
    st.radio("Listed companies found", range(len(results)), index=None, key="pre-figi-pick", on_change=pick_figi,
             args=(results,), format_func=lambda i: " \u00b7 ".join(
                 x for x in (results[i]["name"], results[i]["ticker"], results[i]["exchange"]) if x))
    st.caption("OpenFIGI gives no ISIN. Enter it if known.")


def pre_investment() -> None:
    try:
        scores = rules.index_scores(db.scores())
        status = db.ai_status()
        everyone = db.holdings(candidates=True)
    except db.DataError as e:
        st.error(str(e))
        return
    remaining = int(status["remaining"])
    restore_form()
    with st.container(border=True, key="panel-pre"):
        if "_pre_error" in state:
            st.error(state.pop("_pre_error"))
        listed = company_list.suggestions()
        a, b, c = st.columns([2, 1, 1])
        picked = a.selectbox("Company", list(listed), index=None, key="pre-company", accept_new_options=True,
                             placeholder="Type a company name", on_change=fill_company, args=(listed,),
                             help="Suggestions from a list of large listed companies. Any other name can be entered.")
        isin = b.text_input("ISIN (optional)", key="pre-isin")
        ticker = c.text_input("Ticker (optional)", key="pre-ticker")
        name = listed[picked]["name"] if picked in listed else (picked or "")
        if picked and picked not in listed:
            figi_search(picked)
            if state.get("pre-figi-for") == picked and state.get("pre-figi-name"):
                name = state["pre-figi-name"]
        chosen, planned, templates, pending = criteria_field("pre-criteria")
        name, isin, ticker = name.strip(), isin.strip().upper().replace(" ", ""), ticker.strip().upper()
        match = importers.find_company(everyone, isin=isin if importers.valid_isin(isin) else "", ticker=ticker, name=name) \
            if name else None
        if pending:
            st.write("Create or remove the new criterion first.")
        elif isin and not importers.valid_isin(isin):
            st.error("The ISIN is not valid.")
        elif match and match["type"] != "candidate":
            st.info(f"{match['name']} is already in the investment universe. Use Holding Screening.")
        elif not name or not chosen:
            st.write("Enter a company and select at least one criterion.")
        elif db.is_read_only():
            st.info("AI checks are not available in the demo account.")
        elif not remaining:
            st.info(service.BUDGET_MESSAGE if not int(status["budget"]) else service.limit_message(status))
        else:
            n = min(len(planned), remaining)
            st.write(f"This will run {n} {'check' if n == 1 else 'checks'}. {remaining} remaining today.")
        ready = bool(name and chosen and not pending and remaining and key and not db.is_read_only()
                     and not (isin and not importers.valid_isin(isin)) and not (match and match["type"] != "candidate"))
        if st.button("Run screening", type="primary", disabled=not ready):
            new = [x for x in planned if x["id"] not in {y["id"] for y in criteria}]
            for x in new:
                x["active"] = False
            try:
                db.save_criteria(new)
                if match is None:
                    db.save_holdings([{"name": name, "ticker": ticker or None, "isin": isin or None, "weight": 0,
                                       "type": "candidate", "pre_investment": True, "decision": "review"}])
                    company = next(h for h in db.holdings(candidates=True) if h["type"] == "candidate" and h["name"] == name
                                   and (h.get("isin") or "") == isin)
                else:
                    company = match
                    if not company.get("pre_investment"):
                        db.save_holdings([{**company, "pre_investment": True,
                                           "decision": company.get("decision") or "review"}])
            except (db.DataError, StopIteration):
                st.error("The company could not be saved.")
                return
            keep_form()
            jobs = runner.build_jobs([company], planned, scores, web=True)[:remaining]
            state.screening_run = runner.new_run(jobs, web=True, estimate=estimate, kind="pre")
            state.screening_run["company_id"] = company["id"]
            st.rerun()


def pre_results_actions(run) -> None:
    company_id = run.get("company_id")
    current = next((h for h in db.holdings(candidates=True) if h["id"] == company_id), None)
    if current is None:
        return
    with st.container(border=True, key="panel-pre-add"):
        if current["type"] == "candidate":
            st.write(f"{current['name']} is a pre-investment company. It is not part of the investment universe.")
            st.button("Add to universe as prospect", type="primary", on_click=add_as_prospect, args=(company_id,),
                      disabled=db.is_read_only())
        else:
            st.write(f"{current['name']} is in the investment universe as a {current['type']}.")


def _history_changed(rows, version) -> None:
    """Saves decisions edited in the list, or opens the profile of a ticked company."""
    edits = state.get(f"pre-history-{version}", {}).get("edited_rows", {})
    everyone = {h["id"]: h for h in db.holdings(candidates=True)}
    try:
        for i, change in edits.items():
            row = rows[int(i)]
            if change.get("Open"):
                state[ui.COMPANY_KEY], state[ui.GOTO_KEY] = row["holding_id"], "views/company.py"
            label = change.get("Decision")
            if label:
                decision = next(k for k, v in preinvest.DECISIONS.items() if v == label)
                db.save_holdings([preinvest.decision_change(everyone[row["holding_id"]], decision)])
                state["_pre_notice"] = f"Decision for {row['company']} saved."
    except db.DataError as e:
        state["_pre_error"] = str(e)
    state["pre-history-version"] = version + 1


def pre_history() -> None:
    try:
        rows = preinvest.history(db.holdings(candidates=True), criteria, rules.index_scores(db.scores()), db.findings(), db.notes())
    except db.DataError as e:
        st.error(str(e))
        return
    if not rows:
        return
    version = state.setdefault("pre-history-version", 0)
    with st.container(border=True, key="panel-pre-history"):
        st.subheader("Previous Pre-investment Screenings", anchor=False)
        if "_pre_notice" in state:
            st.caption(state.pop("_pre_notice"))
        st.data_editor(
            pd.DataFrame([{
                "Open": False, "Date": r["date"], "Company": r["company"], "Result": rules.LABELS[r["result"]],
                "Criteria": r["criteria"], "Summary": r["summary"], "Decision": preinvest.DECISIONS[r["decision"]],
                "In universe": "Prospect" if r["in_universe"] else "", "Note": r["note"],
            } for r in rows]),
            key=f"pre-history-{version}", hide_index=True, on_change=_history_changed, args=(rows, version),
            column_order=["Open", "Date", "Company", "Result", "Decision", "Note", "Summary", "Criteria", "In universe"],
            disabled=["Date", "Company", "Result", "Criteria", "Summary", "In universe", "Note"] + (
                ["Decision"] if db.is_read_only() else []),
            column_config={
                "Open": st.column_config.CheckboxColumn("Open", help="Opens the Company Profile.", width=70),
                "Note": st.column_config.TextColumn(width="medium"),
                "Decision": st.column_config.SelectboxColumn(options=list(preinvest.DECISIONS.values()), required=True),
                "Summary": st.column_config.TextColumn(width="medium"),
            },
        )
        st.download_button("Download history", preinvest.to_xlsx(rows), "redline-pre-investment.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


SECTIONS = {"monitoring": "Portfolio Monitoring", "holding": "Holding Screening", "pre": "Pre-investment Screening"}

run = state.get("screening_run")
if run and (run["active"] or run["current"]):
    progress()
else:
    if run:
        state.setdefault("screening-section", {"monitor": "monitoring", "pre": "pre"}.get(run.get("kind"), "holding"))
    if state.get("screening-section") not in SECTIONS:
        state["screening-section"] = "monitoring"
    section = state["screening-section"]
    if section == "monitoring":
        portfolio_monitoring()
    elif section == "pre":
        pre_investment()
    else:
        holding_screening()
    kind = {"monitor": "monitoring", "pre": "pre"}.get((run or {}).get("kind"), "holding")
    if run and kind == section:
        record_monitoring(run)
        if section == "pre":
            pre_results_actions(run)
        results(run)
    if section == "pre":
        pre_history()

st.caption(AI_NOTE)
