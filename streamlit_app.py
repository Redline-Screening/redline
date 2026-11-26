"""Redline: entry point, sign-in gate and navigation."""
import streamlit as st

from redline import auth, db, ui

st.set_page_config(page_title="Redline", page_icon="assets/redline-icon.svg", layout="wide")
ui.apply_style()

missing = auth.missing_settings()
if missing:
    st.error("Configuration incomplete. Missing settings: " + ", ".join(missing))
    st.stop()

try:
    user = auth.current_user()
except auth.SignInError as e:
    st.error(str(e))
    st.stop()

if user is None:
    st.navigation([st.Page("views/landing.py", title="Redline")], position="hidden").run()
    st.stop()

try:
    demo = db.is_read_only()
except db.DataError as e:
    st.error(str(e))
    st.stop()

page = st.navigation(
    [
        st.Page("views/overview.py", title="Overview", default=True),
        st.Page("views/universe.py", title="Investment Universe", url_path="universe"),
        st.Page("views/criteria.py", title="Exclusion Criteria", url_path="criteria"),
        st.Page("views/sources.py", title="Data Sources", url_path="sources"),
        st.Page("views/screening.py", title="Screening"),
        st.Page("views/company.py", title="Company Profiles", url_path="company"),
        st.Page("views/alerts.py", title="Alerts"),
        st.Page("views/help.py", title="Help", url_path="help"),
    ],
    position="hidden",
)
# Links to a company set the selection and open its profile.
target = st.session_state.pop(ui.GOTO_KEY, None)
if target:
    st.switch_page(target)

# Leaving the Screening page pauses a running screening after its current check.
run = st.session_state.get("screening_run")
if run and page.url_path != "screening":
    run["active"] = False

from redline import navigation  # noqa: E402

PAGES = {"universe": "views/universe.py", "criteria": "views/criteria.py", "sources": "views/sources.py",
         "screening": "views/screening.py", "company": "views/company.py", "alerts": "views/alerts.py",
         "help": "views/help.py"}
navigation.sidebar(PAGES.get(page.url_path, "views/overview.py"), user.email or "", demo)
page.run()
