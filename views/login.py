import streamlit as st

from redline import auth, ui
from redline.constants import AI_NOTE

_, middle, _ = st.columns([1, 1.4, 1])
with middle:
    ui.page_header("Redline", "Exclusion screening for fund universes.")
    sign_in_tab, sign_up_tab = st.tabs(["Sign in", "Create account"])

    with sign_in_tab, st.form("sign-in"):
        email = st.text_input("Email", autocomplete="email")
        password = st.text_input("Password", type="password", autocomplete="current-password")
        if st.form_submit_button("Sign in", type="primary", width="stretch"):
            try:
                auth.sign_in(email, password)
            except auth.SignInError as e:
                st.error(str(e))
            else:
                st.rerun()

    with sign_up_tab, st.form("sign-up"):
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

    if auth.demo_available():
        with st.container(border=True, key="panel-demo"):
            st.write("Prepared screening results, without an account. Read-only.")
            if st.button("View demo", width="stretch"):
                try:
                    auth.sign_in_demo()
                except auth.SignInError as e:
                    st.error(str(e))
                else:
                    st.rerun()

    st.caption(AI_NOTE)
