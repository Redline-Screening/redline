from datetime import timedelta

import streamlit as st

from redline import alertlog, db, rules, theme, ui
from redline import alerts as current_view

ui.page_header("Alerts")

try:
    holdings = db.holdings()
    criteria = db.criteria()
    log = db.alert_log()
    if not log and not db.is_read_only():
        # Results from before the log existed are entered once, dated at their last monitoring check.
        scores, findings, alerts = rules.index_scores(db.scores()), db.findings(), db.alerts()
        if current_view.monitoring_view(holdings, criteria, scores, findings, alerts)["has_results"]:
            db.add_log(alertlog.backfill_rows(holdings, criteria, scores, findings, alerts))
            log = db.alert_log()
except db.DataError as e:
    st.error(str(e))
    st.stop()


def open_monitoring() -> None:
    st.session_state["screening-section"] = "monitoring"
    st.session_state[ui.GOTO_KEY] = "views/screening.py"


if not log:
    with st.container(border=True, key="panel-alerts-empty"):
        st.write("No monitoring results yet.")
        st.button("Open Portfolio Monitoring", type="primary", on_click=open_monitoring)
    st.stop()

today = alertlog.today()
with st.container(border=True, key="panel-filter"):
    a, b, c = st.columns([1.3, 1, 1])
    with a:
        choice = st.segmented_control("Period", ["7", "30", "custom"], default="7", required=True, key="alerts-period",
                                      format_func={"7": "Last 7 days", "30": "Last 30 days", "custom": "Custom range"}.get)
        start = end = None
        if choice == "custom":
            picked = st.date_input("Dates", value=(today - timedelta(days=6), today), max_value=today, key="alerts-range")
            start, end = (picked[0], picked[-1]) if isinstance(picked, (tuple, list)) and picked else (today, today)
    names = {r["holding_id"]: r["issuer"] for r in log}
    companies = b.multiselect("Company", sorted(names, key=names.get), format_func=names.get, key="alerts-companies")
    labels = {r["criterion_id"]: r["criterion"] for r in log if r["criterion_id"]}
    picked_criteria = c.multiselect("Criterion", sorted(labels, key=labels.get), format_func=labels.get, key="alerts-criteria")
    first, last = alertlog.period(choice, start, end, today)
    rows = alertlog.select(log, first, last, companies, picked_criteria)
    st.download_button("Download log", alertlog.to_xlsx(rows), f"redline-alert-log-{first}-{last}.xlsx", type="primary",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", disabled=not rows,
                       help=f"Entries in this view: {len(rows)}.")


def entry(r) -> None:
    with st.container(horizontal=True, vertical_alignment="center"):
        st.markdown(f"**{ui.md_escape(r['criterion'] or 'Provider incident')}**")
        if r["status"] == "provider":
            st.badge("Provider incident", color="gray")
        else:
            theme.show_pill(r["status"])
        if r["change"] and r["change"] != "Unchanged":
            st.badge(r["change"], color="blue")
    if r.get("summary"):
        st.text(r["summary"])
    facts = [f"Severity: {r['severity']}" if r.get("severity") else "", alertlog.ORIGINS[r["origin"]]]
    st.caption(" | ".join(x for x in facts if x))
    if r.get("sources"):
        with st.container(horizontal=True):
            for i, s in enumerate(r["sources"]):
                st.link_button(ui.md_escape(s["url"].split("/")[2].removeprefix("www.")), s["url"], type="tertiary")


if not rows:
    with st.container(border=True, key="panel-alerts-none"):
        st.write("No alerts in this period.")
for day, boxes in alertlog.by_day(rows):
    st.subheader(alertlog.day_label(day, today), anchor=False)
    for box, title in (("breach", "Breaches"), ("watch", "Watch")):
        if not boxes[box]:
            continue
        with st.container(border=True, key=f"panel-{day}-{box}"):
            st.markdown(f"**{title}**")
            for i, card in enumerate(boxes[box]):
                with st.container(border=True, key=f"panel-{day}-{box}-{i}"):
                    st.markdown(f"**{ui.md_escape(card['issuer'])}**")
                    for r in card["entries"]:
                        entry(r)
                    if card["holding_id"] in {h["id"] for h in holdings}:
                        ui.company_link(card["holding_id"], "Company profile", key=f"profile-{day}-{box}-{i}")
