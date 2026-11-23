import pandas as pd
import streamlit as st

from redline import db, providers, ui

ui.page_header("Alerts", "Incidents linked to the exclusion criteria.")

try:
    alerts = db.alerts()
    labels = {c["id"]: c["label"] for c in db.criteria()}
except db.DataError as e:
    st.error(str(e))
    st.stop()

if not alerts:
    ui.empty_panel("alerts", "No alerts recorded.")
    st.stop()

with st.container(border=True, key="panel-alerts"):
    st.dataframe(
        pd.DataFrame([
            {"Date": a["date"], "Severity": a["severity"].capitalize(), "Company": ", ".join(a["tickers"]),
             "Title": a["title"], "Criteria": ", ".join(labels[i] for i in a["criteria"] if i in labels),
             "Origin": a["source"], "Status": a["status"].capitalize(), "Source": providers.safe_url(a["url"])}
            for a in alerts
        ]),
        hide_index=True, placeholder="",
        column_config={"Source": st.column_config.LinkColumn(display_text="Open")},
    )
