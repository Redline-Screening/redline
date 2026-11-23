from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest
from supabase_auth.errors import AuthApiError
from pathlib import Path

APP = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


class FakeTable:
    """Small stand-in for the Supabase query builder."""

    def __init__(self, rows):
        self.rows, self.op, self.match = rows, "select", lambda r: True
        self.span = None

    def select(self, *_): return self
    def order(self, *_, **__): return self

    def range(self, a, b):
        self.span = (a, b + 1)
        return self

    def upsert(self, records, **_):
        self.op, self.records = "upsert", records
        return self

    def delete(self):
        self.op = "delete"
        return self

    def in_(self, col, values):
        self.match = lambda r: r[col] in values
        return self

    def execute(self):
        if self.op == "upsert":
            for rec in self.records:
                rec = {"id": f"new{len(self.rows)}", **rec}
                old = next((r for r in self.rows if r["id"] == rec["id"]), None)
                old.update(rec) if old else self.rows.append(rec)
        elif self.op == "delete":
            self.rows[:] = [r for r in self.rows if not self.match(r)]
        data = [dict(r) for r in self.rows if self.match(r)]
        return SimpleNamespace(data=data[slice(*self.span)] if self.span else data)


class FakeClient:
    def __init__(self, signed_in):
        self.auth, self.tables = FakeAuth(signed_in), {}

    def table(self, name):
        return FakeTable(self.tables.setdefault(name, []))


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
        app = AppTest.from_file(APP, default_timeout=20)
        for k in ("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SIGNUP_ACCESS_CODE"):
            app.secrets[k] = ("the-code" if k == "SIGNUP_ACCESS_CODE" else "x") if secrets else ""
        app.session_state["_supabase"] = FakeClient(signed_in)
        return app.run()

    return make
