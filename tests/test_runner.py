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
        return NS(**{**vars(result_for(company, criteria, new=[{"id": "x", "criterion_id": "c1"}])), "alerts": [1]})
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

    def check(sb, client, company, criteria, **k):
        gate.wait(5)
        return result_for(company, criteria)
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
    assert any("Reported: 2026-05-18" in c.value.replace("\\", "") for c in app.caption)
    assert list(app.dataframe[0].value["Status"]) == ["Breach"]


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


def test_latest_run_on_the_page(make_app, monkeypatch):
    f_new = stored(id="n1", holding_id="h2", criterion_id="c1", title="Fresh finding", severity="medium")
    f_old = stored(id="f0", holding_id="h1", criterion_id="c1", title="Other company", severity="high")
    f_low = stored(id="f5", holding_id="h2", criterion_id="c1", title="Older high finding", severity="high")

    def check(sb, client, company, criteria, **k):
        c = criteria[0]
        new = [f_new] if (company["id"], c["id"]) == ("h2", "c1") else []
        return result_for(company, criteria, new=new, scores={c["id"]: {"controversy": {"level": "medium" if new else "none"}}})
    monkeypatch.setattr(service, "run_check", check)
    monkeypatch.setattr(service, "claude", lambda key: None)
    s1 = {"holding_id": "h1", "criterion_id": "c1", "exposure": 0, "exposure_kind": "analyst", "controversy": {"level": "none"}}
    s2 = {"holding_id": "h2", "criterion_id": "c1", "controversy": {"level": "medium", "checked": "2026-11-26"}}
    app = open_page(make_app, findings=[f_old, f_new, f_low], scores=[s1, s2])
    app.multiselect[0].unselect("c2").run()
    app.segmented_control[0].set_value("selected").run()
    app.multiselect[0].select("h2").run()
    app.checkbox[0].uncheck().run()
    click(app, "Run screening")
    for _ in range(8):
        time.sleep(0.05)
        app.run()
    assert not app.exception
    latest = app.dataframe[0].value
    assert list(latest["Change"]) == ["Not screened → Watch"]
    assert list(latest["New findings"]) == [1]
    results = app.dataframe[1].value
    assert list(results["Company"]) == ["B"]
    app.toggle[0].set_value(True).run()
    assert sorted(app.dataframe[1].value["Company"]) == ["A", "B"]
    assert app.selectbox[0].value == "h2"
    titles = [t.value for t in app.text if t.value in ("Fresh finding", "Older high finding")]
    assert titles == ["Fresh finding", "Older high finding"]
    assert any("badge[New]" in m.value for m in app.markdown)


def test_no_incidents_message(make_app, monkeypatch):
    monkeypatch.setattr(service, "run_check", lambda sb, client, company, criteria, **k: result_for(company, criteria))
    monkeypatch.setattr(service, "claude", lambda key: None)
    app = open_page(make_app)
    app.multiselect[0].unselect("c2").run()
    app.segmented_control[0].set_value("selected").run()
    app.multiselect[0].select("h1").run()
    click(app, "Run screening")
    for _ in range(8):
        time.sleep(0.05)
        app.run()
    assert list(app.dataframe[0].value["Note"]) == ["No incidents found for A / Military"]
    assert any("No incidents found for A / Military in the latest run." in c.value for c in app.caption)


def run_pages(app, steps=8):
    for _ in range(steps):
        time.sleep(0.05)
        app.run()
    assert not app.exception


@pytest.mark.parametrize("fails", [True, False])
def test_findings_open_on_the_checked_company(make_app, monkeypatch, fails):
    def check(sb, client, company, criteria, **k):
        if fails:
            raise screening.ScreeningError("The AI answer was incomplete (output limit reached). Nothing was saved.")
        return result_for(company, criteria)
    monkeypatch.setattr(service, "run_check", check)
    monkeypatch.setattr(service, "claude", lambda key: None)
    other = stored(id="f0", holding_id="h2", criterion_id="c1", title="Other company")
    app = open_page(make_app, findings=[other])
    assert app.selectbox[0].value == "h2"
    app.multiselect[0].unselect("c1").run()
    app.segmented_control[0].set_value("selected").run()
    app.multiselect[0].select("h1").run()
    click(app, "Run screening")
    run_pages(app)
    assert app.selectbox[0].value == "h1"
    note = [c.value for c in app.caption if "A / Child labour" in c.value]
    if fails:
        assert note == ["Check failed for A / Child labour: The AI answer was incomplete (output limit reached). Nothing was saved."]
    else:
        assert note == ["No incidents found for A / Child labour in the latest run."]
