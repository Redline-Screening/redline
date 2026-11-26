import streamlit as st

from redline import alerts as view
from redline import db, rules, ui

ui.page_header("Alerts", "Results of Portfolio Monitoring and provider incidents.")

try:
    holdings = db.holdings()
    criteria = db.criteria()
    data = view.monitoring_view(holdings, criteria, rules.index_scores(db.scores()), db.findings(), db.alerts())
except db.DataError as e:
    st.error(str(e))
    st.stop()


def open_monitoring() -> None:
    st.session_state["screening-section"] = "monitoring"
    st.session_state[ui.GOTO_KEY] = "views/screening.py"


if not data["has_results"]:
    with st.container(border=True, key="panel-alerts-empty"):
        st.write("No monitoring results yet.")
        st.button("Open Portfolio Monitoring", type="primary", on_click=open_monitoring)
    st.stop()

with st.container(border=True, key="panel-filter"):
    a, b = st.columns(2)
    names = {card["company"]["id"]: card["company"]["name"] for box in ("breach", "watch") for card in data[box]}
    companies = a.multiselect("Company", sorted(names, key=names.get), format_func=names.get)
    labels = {c["id"]: c["label"] for c in criteria if c["active"]}
    picked = b.multiselect("Criterion", list(labels), format_func=labels.get)


def card(item, box, i) -> None:
    with st.container(border=True, key=f"panel-alert-{box}-{i}"):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown(f"**{ui.md_escape(item['company']['name'])}**")
            if item["new"]:
                st.badge("New", color="blue")
        for line in item["lines"]:
            st.markdown(f"{ui.md_escape(line['criterion']['label'])}")
            if line["summary"]:
                st.text(line["summary"])
            else:
                st.caption("Summary available after the next check")
            facts = [f"Findings: {line['findings']}", f"Last monitoring check: {line['checked']}"]
            if line["new"]:
                facts.insert(0, "New since the last monitoring run")
            st.caption(" | ".join(facts))
        for p in item["provider"]:
            st.caption(" | ".join(x for x in ("Provider incident", p["severity"].capitalize(), p["date"] or "Date unknown") if x))
            st.text(p["title"])
        ui.company_link(item["company"]["id"], "Company profile", key=f"profile-{box}-{i}")


for box, title in (("breach", "Breaches"), ("watch", "Watch")):
    cards = view.select(data[box], companies, picked)
    with st.container(border=True, key=f"panel-box-{box}"):
        st.subheader(title, anchor=False)
        st.caption("Action required." if box == "breach" else "Developments to follow.")
        if not cards:
            st.write("None.")
        for i, item in enumerate(cards):
            card(item, box, i)
