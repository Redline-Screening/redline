import streamlit as st

from redline import alerts as rules
from redline import db, ui
from redline.constants import FINDING_CATEGORIES

PAGE = 20

ui.page_header("Alerts", "Incidents of medium severity or above and imported provider incidents.")

try:
    criteria = db.criteria()
    entries = rules.join(db.alerts(), db.findings(), db.holdings(), criteria)
except db.DataError as e:
    st.error(str(e))
    st.stop()

if not entries:
    ui.empty_panel("alerts", "No alerts recorded.")
    st.stop()

open_alerts = rules.select(entries)
a, b, c = st.columns(3)
a.metric("Open alerts", len(open_alerts), border=True)
b.metric("Severe or high", sum(e["severity"] in ("severe", "high") for e in open_alerts), border=True)
c.metric("Companies affected", len({n for e in open_alerts for n in e["companies"]}), border=True)

with st.container(border=True, key="panel-filter"):
    view = st.segmented_control("Show", ["open", "all"], default="open", required=True, label_visibility="collapsed",
                                format_func={"open": "Open", "all": "All"}.get)
    a, b, c = st.columns(3)
    severities = a.multiselect("Severity", rules.SEVERITIES, format_func=str.capitalize)
    companies = b.multiselect("Company", sorted({n for e in entries for n in e["companies"]}))
    labels = {x["id"]: x["label"] for x in criteria}
    picked = c.multiselect("Criterion", list(labels), format_func=labels.get)

shown = rules.select(entries, open_only=view == "open", severities=severities, companies=companies, criteria=picked)
st.caption(f"{len(shown)} of {len(entries)} alerts. AI summaries are generated from the linked sources.")

limit = st.session_state.setdefault("alerts_limit", PAGE)
for e in shown[:limit]:
    if e["date_type"]:
        date = ui.finding_date(e)
    else:
        date = f"Date: {e['date']}" if e["date"] else "Date unknown"
    ui.incident_card(
        e["id"], e["title"],
        [", ".join(e["companies"]), ", ".join(e["criteria"]) or "No criterion", f"Severity: {e['severity']}",
         FINDING_CATEGORIES.get(e["category"]), date, *(ui.evidence_facts(e["finding"]) if e["finding"] else []), e["origin"], f"Status: {e['status']}"],
        e["summary"], e["sources"],
    )
    for n, hid in enumerate(e["holding_ids"][:1]):
        ui.company_link(hid, "Company profile", key=f"profile-{e['id']}-{n}")
if len(shown) > limit and st.button("Show more"):
    st.session_state.alerts_limit = limit + PAGE
    st.rerun()
