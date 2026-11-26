"""Redline: entry point, sign-in gate and navigation."""
import streamlit as st

from redline import auth, db, ui

st.set_page_config(page_title="Redline", layout="wide")
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
    st.navigation([st.Page("views/login.py", title="Sign In")], position="hidden").run()
    st.stop()

try:
    demo = db.is_read_only()
except db.DataError as e:
    st.error(str(e))
    st.stop()

page = st.navigation(
    {
        "Portfolio": [
            st.Page("views/overview.py", title="Overview", default=True),
        ],
        "Setup": [
            st.Page("views/universe.py", title="1. Investment Universe", url_path="universe"),
            st.Page("views/criteria.py", title="2. Exclusion Criteria", url_path="criteria"),
            st.Page("views/sources.py", title="3. Data Sources", url_path="sources"),
        ],
        "Analysis": [
            st.Page("views/screening.py", title="Screening"),
            st.Page("views/company.py", title="Company Profiles", url_path="company"),
            st.Page("views/alerts.py", title="Alerts"),
        ],
    }
)
# Links to a company set the selection and open its profile.
target = st.session_state.pop(ui.GOTO_KEY, None)
if target:
    st.switch_page(target)

# Leaving the Screening page pauses a running screening after its current check.
run = st.session_state.get("screening_run")
if run and page.url_path != "screening":
    run["active"] = False

with st.sidebar:
    if demo:
        st.text("Demo account")
        st.caption("Read-only. Prepared results; AI checks are not available.")
    else:
        st.text(user.email or "")
    st.button("Sign out", on_click=auth.sign_out, key="sign-out")
page.run()
