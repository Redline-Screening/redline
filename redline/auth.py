"""Sign-in with Supabase email accounts.

Each browser session has its own Supabase client in st.session_state. It must
never be cached with st.cache_resource, which is shared between users.
"""
import hmac

import streamlit as st
from supabase import Client, ClientOptions, create_client
from supabase_auth.errors import AuthApiError, AuthError, AuthRetryableError

_CLIENT = "_supabase"
REQUIRED = ("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SIGNUP_ACCESS_CODE")


class SignInError(Exception):
    """Message suitable for display."""


def missing_settings() -> list[str]:
    try:
        return [k for k in REQUIRED if not st.secrets.get(k)]
    except FileNotFoundError:
        return list(REQUIRED)


def client() -> Client:
    if _CLIENT not in st.session_state:
        st.session_state[_CLIENT] = create_client(
            st.secrets["SUPABASE_URL"],
            st.secrets["SUPABASE_PUBLISHABLE_KEY"],
            ClientOptions(auto_refresh_token=False),
        )
    return st.session_state[_CLIENT]


def current_user():
    """Signed-in user or None. Refreshes the access token when it is about to expire."""
    try:
        session = client().auth.get_session()
    except AuthRetryableError as e:
        raise SignInError("The sign-in service is not reachable. Try again shortly.") from e
    except AuthError:
        st.session_state.clear()
        return None
    return session.user if session else None


def _message(e: AuthError) -> str:
    code = getattr(e, "code", None)
    return {
        "invalid_credentials": "Email or password is incorrect.",
        "email_not_confirmed": "Confirm the email address before signing in.",
        "user_already_exists": "An account with this email already exists.",
        "email_address_invalid": "The email address is not valid.",
        "over_request_rate_limit": "Too many attempts. Try again later.",
        "over_email_send_rate_limit": "Too many attempts. Try again later.",
    }.get(code, str(e) if isinstance(e, AuthApiError) else "The request could not be completed.")


def sign_in(email: str, password: str) -> None:
    if not email.strip() or not password:
        raise SignInError("Enter an email address and a password.")
    try:
        client().auth.sign_in_with_password({"email": email.strip(), "password": password})
    except AuthError as e:
        raise SignInError(_message(e)) from e


def sign_up(email: str, password: str, code: str) -> bool:
    """Create an account. Returns True when the user is signed in directly."""
    if not email.strip() or not password:
        raise SignInError("Enter an email address and a password.")
    expected = str(st.secrets["SIGNUP_ACCESS_CODE"])
    if not hmac.compare_digest(code.strip().encode(), expected.encode()):
        raise SignInError("The access code is not valid.")
    try:
        result = client().auth.sign_up({"email": email.strip(), "password": password})
    except AuthError as e:
        raise SignInError(_message(e)) from e
    return result.session is not None


def sign_out() -> None:
    try:
        client().auth.sign_out({"scope": "local"})
    except AuthError:
        pass
    st.session_state.clear()
