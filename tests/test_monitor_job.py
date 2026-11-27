"""The daily monitoring job (monitor.py) with a simulated database and AI."""
from datetime import date, datetime
from types import SimpleNamespace as NS

import pytest
from conftest import FakeClient
from test_runner import C1, result_for

import monitor
from redline import alertlog, screening, service

TODAY = date(2026, 11, 28)
U1, U2, DEMO = "u1", "u2", "u3"


class JobClient(FakeClient):
    """Secret-key client: sees every user's rows; records the job's RPC calls."""

    def __init__(self, global_left=10):
        super().__init__(True)
        self.calls, self.global_left = [], global_left

    def rpc(self, name, args=None):
        self.calls.append((name, args))
        if name == "reserve_monitor_check_for":
            if self.global_left < 1:
                return NS(execute=lambda: NS(data={"reason": "daily"}))
            self.global_left -= 1
            return NS(execute=lambda: NS(data={"id": f"t{len(self.calls)}"}))
        if name == "can_summarize_for":
            return NS(execute=lambda: NS(data=False))
        return NS(execute=lambda: NS(data=None))


def company(i, uid, monitored=True, kind="holding"):
    return {"id": f"{uid}-h{i}", "user_id": uid, "name": f"Company {i}", "weight": 10 - i, "type": kind, "monitored": monitored}


def setup(sb):
    crit = lambda uid: {**C1, "id": f"{uid}-c1", "user_id": uid}  # noqa: E731
    sb.tables.update(
        workspaces=[{"user_id": U1, "monitor": {"enabled": True}}, {"user_id": U2, "monitor": {"enabled": False}},
                    {"user_id": DEMO, "monitor": {"enabled": True}}],
        accounts=[{"user_id": DEMO, "read_only": True}],
        holdings=[company(1, U1), company(2, U1), company(3, U1, monitored=False), company(4, U1, kind="prospect"),
                  company(1, U2), company(1, DEMO)],
        criteria=[crit(U1), {**crit(U1), "id": "u1-off", "active": False}, crit(U2), crit(DEMO)],
        scores=[], findings=[], alert_log=[])


@pytest.fixture
def job(monkeypatch):
    sb = JobClient()
    setup(sb)
    seen = []

    def check(sb_, client, company_, criteria, **k):
        seen.append((company_["id"], [c["id"] for c in criteria], k))
        if company_["id"] == "u1-h2":
            raise screening.ScreeningError("busy")
        sb_.tables["scores"].append({"user_id": k["uid"], "holding_id": company_["id"], "criterion_id": criteria[0]["id"],
                                     "controversy": {"level": "high"}})
        return result_for(company_, criteria, scores={criteria[0]["id"]: {"controversy": {"level": "high"}}})
    monkeypatch.setattr(service, "run_check", check)
    monkeypatch.setattr(service, "claude", lambda key: None)
    monkeypatch.setattr(alertlog, "today", lambda: TODAY)
    monkeypatch.setattr(monitor, "datetime", NS(now=lambda tz: datetime(2026, 11, 28, 7, 5)))
    monkeypatch.setattr("supabase.create_client", lambda url, key: sb)
    for k in ("SUPABASE_URL", "SUPABASE_SECRET_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(k, "x")
    return sb, seen


def test_runs_only_selected_holdings_of_enabled_users(job, capsys):
    sb, seen = job
    assert monitor.main([]) == 0
    assert [s[0] for s in seen] == ["u1-h1", "u1-h2"]                  # not unmonitored, prospects, disabled or demo users
    assert seen[0][1] == ["u1-c1"]                                       # active criteria only
    options = seen[0][2]
    assert (options["kind"], options["model"], options["max_searches"], options["uid"]) == ("monitor", "claude-haiku-5-5", 2, U1)
    ws = sb.tables["workspaces"][0]
    assert (ws["monitor_last_run"], ws["monitor_last_kind"]) == ("2026-11-28", "automatic")
    assert ws["monitor_note"] == "Automatic run: 1 checks, 1 failed."
    log = sb.tables["alert_log"]
    assert [(r["issuer"], r["user_id"], r["day"]) for r in log] == [("Company 1", U1, "2026-11-28")]
    out = capsys.readouterr().out
    assert "Company" not in out and "@" not in out                       # the public log has counts only


def test_once_per_day_unless_again(job):
    sb, seen = job
    monitor.main([])
    monitor.main([])
    assert len(seen) == 2
    monitor.main(["--again"])
    assert len(seen) == 4


def test_waits_for_seven_unless_forced(job, monkeypatch):
    sb, seen = job
    monkeypatch.setattr(monitor, "datetime", NS(now=lambda tz: datetime(2026, 11, 28, 6, 5)))
    monitor.main([])
    assert seen == []
    monitor.main(["--force"])
    assert len(seen) == 2


def test_daily_limit_stops_the_run(monkeypatch):
    sb = JobClient(global_left=1)
    setup(sb)
    monkeypatch.setattr(service, "claude", lambda key: None)
    monkeypatch.setattr(alertlog, "today", lambda: TODAY)

    # Use the real run_check with a simulated AI so the reservation path is exercised.
    from test_screening import URL, Fake, answer as build, reply, search, text
    client = Fake(reply(search(URL), text(build(cid="u1-c1"))), reply(search(URL), text(build(cid="u1-c1"))))
    counts = monitor.run_user(sb, client, U1, TODAY)
    assert counts["done"] == 1 and counts["stopped"] == service.LIMIT_MESSAGE
    reserve = [a for n, a in sb.calls if n == "reserve_monitor_check_for"]
    assert reserve[0] == {"p_uid": U1, "p_model": "claude-haiku-5-5"}
    finish = [a for n, a in sb.calls if n == "finish_ai_check_for"]
    assert finish[0]["p_uid"] == U1 and finish[0]["p_status"] == "done"
    assert all(r["user_id"] == U1 for r in sb.tables["scores"])          # written with the user, as the secret key requires


def test_missing_settings(monkeypatch, capsys):
    monkeypatch.setattr(monitor, "datetime", NS(now=lambda tz: datetime(2026, 11, 28, 7, 5)))
    for k in ("SUPABASE_URL", "SUPABASE_SECRET_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert monitor.main([]) == 1
    assert "Missing settings" in capsys.readouterr().out
