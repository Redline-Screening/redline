from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest
from supabase_auth.errors import AuthApiError
from pathlib import Path

APP = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


class FakeAuth:
    def __init__(self, signed_in):
        self.session = self._session() if signed_in else None
        self.sign_ups = 0

    @staticmethod
    def _session():
        return SimpleNamespace(user=SimpleNamespace(id="u1", email="a@example.com"))

    def get_session(self):
        return self.session

    def sign_in_with_password(self, c):
        if c["password"] != "right-password":
            raise AuthApiError("Invalid login credentials", 400, "invalid_credentials")
        self.session = self._session()

    def sign_up(self, c):
        self.sign_ups += 1
        self.session = self._session()
        return SimpleNamespace(session=self.session)

    def sign_out(self, options=None):
        self.session = None


@pytest.fixture
def make_app():
    def make(signed_in=True, secrets=True):
        app = AppTest.from_file(APP)
        for k in ("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SIGNUP_ACCESS_CODE"):
            app.secrets[k] = ("the-code" if k == "SIGNUP_ACCESS_CODE" else "x") if secrets else ""
        app.session_state["_supabase"] = SimpleNamespace(auth=FakeAuth(signed_in))
        return app.run()

    return make
