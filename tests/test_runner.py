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
        return result_for(company, criteria, new=[{"id": "x", "criterion_id": criteria[0]["id"]}])
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








# Latest run
from test_screening import stored  # noqa: E402


def result_for(company, criteria, new=(), updated=(), before=None, known=(), scores=None):
    return NS(new=list(new), updated=list(updated), alerts=[], left_out=0, before=before or {}, known=list(known),
              scores=scores or {c["id"]: {} for c in criteria})


def test_check_records():
    job = {"company": {"id": "h2", "name": "B"}, "criteria": [C1, C2]}
    r = result_for(job["company"], job["criteria"], new=[{"id": "n1", "criterion_id": "c1"}],
                   updated=[{"id": "f1", "criterion_id": "c1"}], known=[stored(), stored(id="f9")],
                   scores={"c1": {"controversy": {"level": "high"}}, "c2": {"controversy": {"level": "none"}}})
    a, b = runner.check_records(job, r)
    assert (a["before"], a["after"], a["new"], a["updated"], a["unchanged"]) == ("na", "breach", ["n1"], ["f1"], 1)
    assert (b["before"], b["after"], b["new"], b["updated"]) == ("na", "clear", [], [])
    assert runner.check_records(job, error="x")[0]["error"] == "x"






def run_pages(app, steps=8):
    for _ in range(steps):
        time.sleep(0.05)
        app.run()
    assert not app.exception

