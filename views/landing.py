"""Landing page before sign-in: no sidebar."""
import streamlit as st

from redline import auth, theme

st.html("<style>[data-testid='stSidebar'],[data-testid='stSidebarCollapsedControl']{display:none}</style>")


@st.dialog("Sign in")
def sign_in() -> None:
    with st.form("sign-in", border=False):
        email = st.text_input("Email", autocomplete="email")
        password = st.text_input("Password", type="password", autocomplete="current-password")
        if st.form_submit_button("Sign in", type="primary", width="stretch"):
            try:
                auth.sign_in(email, password)
            except auth.SignInError as e:
                st.error(str(e))
            else:
                st.rerun()


@st.dialog("Create account")
def sign_up() -> None:
    with st.form("sign-up", border=False):
        email = st.text_input("Email", autocomplete="email")
        password = st.text_input("Password", type="password", autocomplete="new-password")
        code = st.text_input("Access code", type="password", autocomplete="off")
        if st.form_submit_button("Create account", type="primary", width="stretch"):
            try:
                signed_in = auth.sign_up(email, password, code)
            except auth.SignInError as e:
                st.error(str(e))
            else:
                if signed_in:
                    st.rerun()
                st.info("Confirm the email address, then sign in.")


ANALYSIS = [
    ("Portfolio Monitoring", "Checks selected holdings every day for new incidents linked to your criteria. Use it to follow the "
     "portfolio continuously. Runs a new AI check per company each day."),
    ("Holding Screening", "Screens chosen holdings against chosen criteria now, with a new web search. Use it before a review or "
     "after a news event. Runs a new AI check per company and criterion."),
    ("Pre-investment Screening", "Screens a company outside the universe before you invest. Runs a new AI check; the company can "
     "then be added as a prospect."),
    ("Company Profiles", "Shows the stored status, revenue exposure and all findings of a company over time. No new search."),
    ("Alerts", "Shows breaches and companies on watch found by daily monitoring and provider imports. No new search."),
]
STEPS = [
    ("Upload your investment universe", "Import holdings and prospects from a CSV file or add them one by one."),
    ("Define your exclusion criteria", "Choose standard exclusions or define your own revenue limits and breach levels."),
    ("Connect data sources", "Load provider figures and incidents, use AI screening, or combine both."),
    ("Analysis", "Monitor, screen and review your holdings."),
]


def toggle_analysis() -> None:
    st.session_state["landing-analysis"] = not st.session_state.get("landing-analysis", False)


with st.container(key="rl-hero"):
    st.image(theme.logo(light=True), width=480)
    st.html('<p class="rl-statement">Know when your portfolio crosses the line.</p><div class="rl-rule"></div>')
    with st.container(horizontal=True):
        if st.button("Sign in", type="primary"):
            sign_in()
        if st.button("Create account"):
            sign_up()
        if auth.demo_available() and st.button("View demo"):
            try:
                auth.sign_in_demo()
            except auth.SignInError as e:
                st.error(str(e))
            else:
                st.rerun()

with st.container(key="rl-body"):
    with st.container(key="rl-reveal-statement"):
        st.html('<p class="rl-lead">Redline screens your investment universe against your exclusion criteria, combining provider '
                'data with AI web research, and alerts you when a holding crosses a line.</p>')
    for column, (n, (title, text)) in zip(st.columns(4), enumerate(STEPS, start=1)):
        with column, st.container(border=True, key=f"panel-rl-reveal-step-{n}", height="stretch"):
            st.html(f'<p class="rl-step-no">{n}</p><div class="rl-step-line"></div>')
            st.markdown(f"**{title}**")
            st.write(text)
            if n == 4:
                opened = st.session_state.get("landing-analysis", False)
                with st.container(key="rl-analysis-open"):
                    st.button("\u2304" if opened else "\u203a", on_click=toggle_analysis,
                              help="Hide the analysis sections" if opened else "Show the analysis sections")
    if st.session_state.get("landing-analysis", False):
        for title, text in ANALYSIS:
            with st.expander(title):
                st.write(text)
