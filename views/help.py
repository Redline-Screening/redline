import streamlit as st

from redline import theme, ui

ui.page_header("Help")

PAGES = [
    ("Overview", None, "views/overview.py"),
    ("Investment Universe", None, "views/universe.py"),
    ("Exclusion Criteria", None, "views/criteria.py"),
    ("Data Sources", None, "views/sources.py"),
    ("Portfolio Monitoring", "monitoring", "views/screening.py"),
    ("Holding Screening", "holding", "views/screening.py"),
    ("Pre-investment Screening", "pre", "views/screening.py"),
    ("Company Profile", None, "views/company.py"),
    ("Alerts", None, "views/alerts.py"),
]


def go(page, section) -> None:
    if section:
        st.session_state["screening-section"] = section
    st.session_state[ui.GOTO_KEY] = page


with st.container(border=True, key="panel-help"):
    st.subheader("Pages", anchor=False)
    for title, section, page in PAGES:
        st.markdown(f"**{title}**")
        st.write(theme.HELP[title])
        st.button(f"Open {title}", key=f"help-{title}", type="tertiary", on_click=go, args=(page, section))

with st.container(border=True, key="panel-help-status"):
    st.subheader("Status", anchor=False)
    for state, text in (("breach", "A revenue limit is exceeded, or an incident reaches the breach level of the criterion."),
                        ("watch", "An incident below the breach level, an unsourced revenue estimate above the limit, or a "
                                  "likelihood of increase at or above the watch threshold."),
                        ("clear", "Every check of the criterion found no exposure above the limit and no relevant incident."),
                        ("partial", "Some active criteria are clear, others have not been screened."),
                        ("na", "The criterion has not been screened for this company.")):
        with st.container(horizontal=True, vertical_alignment="center"):
            theme.show_pill(state)
            st.write(text)
