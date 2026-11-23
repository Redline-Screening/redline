import threading
import time
from datetime import date
from types import SimpleNamespace as NS

import pytest

from redline import runner, screening, service

C1 = {"id": "c1", "label": "Military", "type": "both", "threshold": 0, "watch_at": 50, "controversy_limit": "high",
      "active": True, "sort": 1, "keywords": []}
C2 = {**C1, "id": "c2", "label": "Child labour", "type": "conduct", "threshold": None}
H = [{"id": "h1", "name": "A", "weight": 1, "type": "holding"}, {"id": "h2", "name": "B", "weight": 9, "type": "holding"}]


def test_jobs():
    jobs = runner.build_jobs(H, [C1, C2], {}, web=True)
    assert [(j["company"]["id"], j["criteria"][0]["id"]) for j in jobs] == [("h2", "c1"), ("h2", "c2"), ("h1", "c1"), ("h1", "c2")]
    quick = runner.build_jobs(H, [C1, C2], {}, web=False)
    assert [len(j["criteria"]) for j in quick] == [1, 1]
    assert runner.build_jobs(H, [C2], {}, web=False) == []


def test_recent_checks_are_skipped():
    scores = {("h2", "c1"): {"controversy": {"checked": "2026-11-20"}}, ("h1", "c1"): {"controversy": {"checked": "2026-11-01"}}}
    jobs = runner.build_jobs(H, [C1], scores, web=True, skip_days=7, today=date(2026, 11, 24))
    assert [j["company"]["id"] for j in jobs] == ["h1"]


def make(n=3):
    return runner.new_run([{"company": {"name": f"N{i}"}, "criteria": [C1]} for i in range(n)], web=True, estimate=True)


def drive(run, steps=10):
    for _ in range(steps):
        t = runner.start_next(run, None, None)
        if t:
            t.join()


def test_no_check_runs_twice(monkeypatch):
    seen, gate = [], threading.Event()

    def check(sb, client, company, criteria, **k):
        seen.append(company["name"])
        gate.wait(5)
        return NS(new=[1], alerts=[])
    monkeypatch.setattr(service, "run_check", check)
    run = make()
    first = runner.start_next(run, None, None)
    assert [runner.start_next(run, None, None) for _ in range(5)] == [None] * 5
    run["active"] = False       # stop during the first check
    gate.set()
    first.join()
    assert (run["done"], len(run["jobs"]), run["current"]) == (1, 2, None)
    assert runner.start_next(run, None, None) is None
    run["active"] = True        # resume
    drive(run)
    assert seen == ["N0", "N1", "N2"] and run["done"] == 3 and not run["active"]


def test_limit_stops_with_message(monkeypatch):
    def check(*a, **k):
        raise service.LimitReached(service.LIMIT_MESSAGE)
    monkeypatch.setattr(service, "run_check", check)
    run = make()
    drive(run)
    assert run["message"] == "Daily AI limit reached, try again tomorrow." and len(run["jobs"]) == 3 and not run["errors"]


@pytest.mark.parametrize("error,left", [(screening.ScreeningError("x"), 1), (RuntimeError("db"), 2)])
def test_failures_stop_the_run(monkeypatch, error, left):
    def check(*a, **k):
        raise error
    monkeypatch.setattr(service, "run_check", check)
    run = make()
    drive(run)
    assert len(run["jobs"]) == left and not run["active"] and run["current"] is None


# Page
def click(app, label):
    next(b for b in app.button if b.label.startswith(label)).click().run()
    assert not app.exception


def texts(app):
    return " ".join(m.value for m in app.markdown)


def open_page(make_app, remaining=15, **k):
    app = make_app(holdings=[dict(h) for h in H], criteria=[dict(C1), dict(C2)], workspaces=[{"user_id": "u1", "mode": "both"}], **k)
    app.session_state["_supabase"].status["remaining"] = remaining
    return app.switch_page("views/screening.py").run()


def test_estimate_and_limit(make_app):
    app = open_page(make_app)
    assert not app.exception
    assert "This will run 4 checks. 15 remaining today." in texts(app)
    assert "funded privately" in app.caption[1].value
    app = open_page(make_app, remaining=3)
    assert "needs 4 checks. 3 remaining today: this will run 3 checks" in texts(app)
    app = open_page(make_app, remaining=0)
    assert app.info[0].value == "Daily AI limit reached, try again tomorrow."
    assert next(b for b in app.button if b.label == "Run screening").disabled


def test_run_to_the_end(make_app, monkeypatch):
    def check(sb, client, company, criteria, **k):
        return NS(new=[1], alerts=[1])
    monkeypatch.setattr(service, "run_check", check)
    monkeypatch.setattr(service, "claude", lambda key: None)
    app = open_page(make_app)
    click(app, "Run screening")
    for _ in range(12):
        time.sleep(0.05)
        app.run()
        assert not app.exception
    assert "Checks completed: 4 of 4. New findings: 4. New alerts: 4." in texts(app)
    click(app, "Close")
    assert "Last Screening" not in [s.value for s in app.subheader]


def test_leaving_the_page_pauses(make_app, monkeypatch):
    gate = threading.Event()

    def check(*a, **k):
        gate.wait(5)
        return NS(new=[], alerts=[])
    monkeypatch.setattr(service, "run_check", check)
    monkeypatch.setattr(service, "claude", lambda key: None)
    app = open_page(make_app)
    click(app, "Run screening")
    app.switch_page("views/overview.py").run()
    gate.set()
    time.sleep(0.1)
    app.switch_page("views/screening.py").run()
    assert not app.exception
    run = app.session_state["screening_run"]
    assert run["done"] == 1 and len(run["jobs"]) == 3 and not run["active"]
    assert any(b.label == "Resume (3 open)" for b in app.button)


def test_findings_are_shown(make_app):
    f = {"id": "f1", "holding_id": "h2", "criterion_id": "c1", "category": "contract", "title": "Title *x*", "summary": "Summary",
         "date": "2026-05-18", "date_type": "reported", "severity": "high", "status": "open", "last_seen": "2026-11-24",
         "sources": [{"url": "https://news.example/a", "title": "t"}]}
    s = {"holding_id": "h2", "criterion_id": "c1", "exposure": 0.2, "source": "AI estimate (web search)", "controversy": {"level": "high", "checked": "2026-11-24"}}
    app = open_page(make_app, findings=[f], scores=[s])
    assert not app.exception
    assert "Title *x*" in [t.value for t in app.text]
    assert any("Reported: 2026-05-18" in c.value for c in app.caption)
    assert list(app.dataframe[0].value["Status"]) == ["Breach"]
