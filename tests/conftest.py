import html
import re
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

    def upsert(self, records, on_conflict="id"):
        self.op, self.records, self.keys = "upsert", records, on_conflict.split(",")
        return self

    def insert(self, records):
        self.op, self.records, self.keys = "upsert", records, ["id"]
        return self

    def update(self, values):
        self.op, self.values = "update", values
        return self

    def delete(self):
        self.op = "delete"
        return self

    def eq(self, col, value):
        before = self.match
        self.match = lambda r: before(r) and r[col] == value
        return self

    def in_(self, col, values):
        self.match = lambda r: r[col] in values
        return self

    def execute(self):
        if self.op == "upsert":
            for rec in self.records:
                rec = dict(rec)
                if self.keys == ["id"]:
                    rec.setdefault("id", f"new{len(self.rows)}")
                old = next((r for r in self.rows if all(r.get(k) == rec.get(k) for k in self.keys)), None)
                old.update(rec) if old else self.rows.append(rec)
        elif self.op == "update":
            for r in self.rows:
                if self.match(r):
                    r.update(self.values)
        elif self.op == "delete":
            self.rows[:] = [r for r in self.rows if not self.match(r)]
        data = [dict(r) for r in self.rows if self.match(r)]
        return SimpleNamespace(data=data[slice(*self.span)] if self.span else data)


class FakeClient:
    def __init__(self, signed_in):
        self.auth, self.tables = FakeAuth(signed_in), {}
        self.status = {"user": 15, "global": 60, "budget": 20, "remaining": 15}
        self.monitor = {"global": 10, "budget": 40, "run_today": False, "read_only": False}

    def table(self, name):
        return FakeTable(self.tables.setdefault(name, []))

    def rpc(self, name, args=None):
        if name == "monitor_status":
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=dict(self.monitor)))
        if name == "start_monitoring_run":
            def start():
                started = not self.monitor["run_today"]
                self.monitor["run_today"] = True
                return SimpleNamespace(data=started)
            return SimpleNamespace(execute=start)
        # Summaries are never generated in tests that use the full page.
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=False if name == "can_summarize" else self.status))


class FakeAuth:
    def __init__(self, signed_in):
        self.session = self._session() if signed_in else None
        self.sign_ups = 0

    @staticmethod
    def _session():
        return SimpleNamespace(user=SimpleNamespace(id="u1", email="a@example.com"), expires_at=None)

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
    def make(signed_in=True, secrets=True, **tables):
        app = AppTest.from_file(APP, default_timeout=20)
        for k in ("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SIGNUP_ACCESS_CODE"):
            app.secrets[k] = ("the-code" if k == "SIGNUP_ACCESS_CODE" else "x") if secrets else ""
        app.secrets["ANTHROPIC_API_KEY"] = "x"
        app.session_state["_supabase"] = FakeClient(signed_in)
        app.session_state["_supabase"].tables.update(tables)
        app.session_state["screening-section"] = "holding"     # tests of Portfolio Monitoring set it themselves
        return app.run()

    return make


def page_title(app) -> str:
    """Title shown in the navy band."""
    for h in app.get("html"):
        m = re.search(r'class="rl-title">(.*?)</p>', h.proto.body)
        if m:
            return html.unescape(m.group(1))
    return ""


def notice(app) -> str:
    return app.toast[0].value if len(app.toast) else ""
