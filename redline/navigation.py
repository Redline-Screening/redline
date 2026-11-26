"""Custom sidebar: logo, large navigation with expanding sections, account links."""
import streamlit as st

from redline import auth, theme

# label, page, screening section
ITEMS = [
    ("Overview", "views/overview.py", None),
    ("Setup", None, [("Investment Universe", "views/universe.py", None), ("Exclusion Criteria", "views/criteria.py", None),
                     ("Data Sources", "views/sources.py", None)]),
    ("Screening", None, [("Portfolio Monitoring", "views/screening.py", "monitoring"),
                         ("Holding Screening", "views/screening.py", "holding"),
                         ("Pre-investment Screening", None, "pre")]),
    ("Company Profiles", "views/company.py", None),
    ("Alerts", "views/alerts.py", None),
]
GOTO = "_goto"


def _go(page, section=None) -> None:
    if section:
        st.session_state["screening-section"] = section
    st.session_state[GOTO] = page


def _toggle(group) -> None:
    open_ = st.session_state.setdefault("nav-open", set())
    open_.symmetric_difference_update({group})


def _active(page, section, current) -> bool:
    if page != current:
        return False
    return section is None or st.session_state.get("screening-section", "monitoring") == section


def sidebar(current: str, email: str, demo: bool) -> None:
    open_ = st.session_state.setdefault("nav-open", set())
    for label, page, children in ITEMS:
        if children and any(p == current for _, p, _ in children):
            open_.add(label)
    active_css = []
    with st.sidebar:
        st.image(theme.logo(), width=170)
        st.write("")
        for label, page, children in ITEMS:
            key = f"nav-{label.lower().replace(' ', '-')}"
            if children:
                arrow = "⌄" if label in open_ else "›"
                st.button(f"{label}  {arrow}", key=key, on_click=_toggle, args=(label,))
                if label in open_:
                    for sub, sub_page, section in children:
                        sub_key = f"nav-sub-{sub.lower().replace(' ', '-')}"
                        st.button(sub, key=sub_key, on_click=_go, args=(sub_page, section), disabled=sub_page is None,
                                  help="Available in a later stage." if sub_page is None else None)
                        if sub_page and _active(sub_page, section, current):
                            active_css.append(sub_key)
            else:
                st.button(label, key=key, on_click=_go, args=(page,))
                if page == current:
                    active_css.append(key)
        st.write("")
        st.write("")
        with st.container(key="rl-account"):
            st.text("Demo account" if demo else email)
            st.button("Help", key="nav-help-link", on_click=_go, args=("views/help.py",))
            if current == "views/help.py":
                active_css.append("nav-help-link")
            st.button("Sign out", key="sign-out", on_click=auth.sign_out)
    st.html("<style>" + "".join(
        f'.st-key-{k} button {{ border-left: 3px solid {theme.RED} !important; }} '
        f'.st-key-{k} button p {{ color: {theme.NAVY} !important; font-weight: 600 !important; }}' for k in active_css) + "</style>")
