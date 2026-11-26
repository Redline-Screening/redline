"""Portfolio Monitoring: Run now with a successful check, one without findings and a failed one."""
import time
from datetime import date

from test_runner import result_for
from test_screening import stored

from redline import runner, screening, service

C1 = {"id": "c1", "key": "military", "label": "Military", "type": "both", "threshold": 0, "watch_at": 50,
      "controversy_limit": "high", "active": True, "sort": 1, "keywords": []}
H = [{"id": f"h{i}", "name": f"Company {i}", "weight": 20 - i, "type": "holding", "monitored": i <= 3} for i in range(1, 13)]
NEW = stored(id="n1", holding_id="h1", criterion_id="c1", title="Monitoring finding", severity="high")


def open_page(make_app, **k):
    app = make_app(holdings=[dict(h) for h in H], criteria=[dict(C1)],
                   workspaces=[{"user_id": "u1", "mode": "ai", "monitor": {"enabled": False}}], **k)
    app.session_state["screening-section"] = "monitoring"
    return app.switch_page("views/screening.py").run()


def finish(app):
    for _ in range(20):
        time.sleep(0.03)
        app.run()
        assert not app.exception
        run = app.session_state["screening_run"]
        if not run["active"] and not run["current"]:
            app.run()
            return


def test_section_shows_coverage_and_cost(make_app):
    app = open_page(make_app)
    assert not app.exception
    assert [s.value for s in app.subheader] == ["Portfolio Monitoring"]
    assert [m.value for m in app.metric] == ["3", "Not yet", "Off", "$0.09"]
    assert app.multiselect[0].value == ["h1", "h2", "h3"]
    assert "This will run 3 checks." in [m.value for m in app.markdown]


def test_toggle_and_selection_are_saved(make_app):
    app = open_page(make_app)
    app.toggle[0].set_value(True).run()
    assert app.session_state["_supabase"].tables["workspaces"][0]["monitor"]["enabled"] is True
    assert app.metric[2].value == "07:00"
    app.multiselect[0].unselect("h3").run()
    monitored = [h["id"] for h in app.session_state["_supabase"].tables["holdings"] if h["monitored"]]
    assert monitored == ["h1", "h2"]


def test_run_now(make_app, monkeypatch):
    calls = []

    def check(sb, client, company, criteria, **k):
        calls.append((company["id"], k))
        time.sleep(0.02)
        if company["id"] == "h3":
            raise screening.ScreeningError("The AI service is busy. Try again in a minute.")
        found = company["id"] == "h1"
        if found:
            sb.tables.setdefault("findings", []).append(dict(NEW))
        return result_for(company, criteria, new=[NEW] if found else [], scores={"c1": {"controversy": {"level": "high" if found else "none"}}})
    monkeypatch.setattr(service, "run_check", check)
    monkeypatch.setattr(service, "claude", lambda key: None)
    app = open_page(make_app)
    next(b for b in app.button if b.label == "Run now").click().run()
    finish(app)
    assert [c[0] for c in calls] == ["h1", "h2", "h3"]
    options = calls[0][1]
    assert (options["kind"], options["model"], options["max_searches"]) == ("monitor", "claude-haiku-5-5", 2)
    assert options["since"] == (date.today().replace(day=date.today().day) - __import__("datetime").timedelta(days=30)).isoformat()
    assert list(app.dataframe[0].value["Status"]) == ["Breach", "Clear", "Failed"]
    assert "Monitoring finding" in [t.value for t in app.text]
    workspace = app.session_state["_supabase"].tables["workspaces"][0]
    assert (workspace["monitor_last_run"], workspace["monitor_last_kind"]) == (date.today().isoformat(), "manual")
    # Once per day.
    assert "Run now is available once per day." in [i.value for i in app.info]
    assert next(b for b in app.button if b.label == "Run now").disabled


def test_daily_cap_limits_the_run(make_app):
    app = make_app(holdings=[dict(h) for h in H], criteria=[dict(C1)], workspaces=[{"user_id": "u1", "mode": "ai"}])
    app.session_state["_supabase"].monitor["global"] = 2
    app.session_state["screening-section"] = "monitoring"
    app.switch_page("views/screening.py").run()
    assert "This will run 2 checks." in [m.value for m in app.markdown]
    app.session_state["_supabase"].monitor["global"] = 0
    app.run()
    assert app.info[0].value == "Daily AI limit reached, try again tomorrow."


def test_since_last_monitoring_check():
    scores = {("h1", "c1"): {"monitor_checked": "2026-11-20"}, ("h2", "c1"): {}}
    jobs = runner.monitoring_jobs(H[:2], [C1], scores, today=date(2026, 11, 26))
    assert [(j["company"]["id"], j["since"]) for j in jobs] == [("h1", "2026-11-20"), ("h2", "2026-10-27")]


def test_mark_monitored(make_app):
    client = make_app(scores=[{"holding_id": "h1", "criterion_id": "c1"}]).session_state["_supabase"]
    result = result_for(H[0], [C1], new=[NEW], scores={"c1": {"controversy": {"level": "high"}}})
    service.mark_monitored(client, H[0], [C1], result)
    row = client.tables["scores"][0]
    assert row["monitor_checked"] == date.today().isoformat() and row["monitor_new"] is True


C2 = {**C1, "id": "c2", "key": "child-labour", "label": "Child labour", "type": "conduct", "threshold": None}


def test_missing_criterion_is_checked_again(make_app, monkeypatch):
    calls = []

    def check(sb, client, company, criteria, **k):
        calls.append([c["id"] for c in criteria])
        covered = criteria[:1] if len(calls) == 1 else criteria       # the first answer leaves out Child labour
        r = result_for(company, covered, scores={c["id"]: {"controversy": {"level": "none"}} for c in covered})
        r.missing = [c for c in criteria if c not in covered]
        return r
    monkeypatch.setattr(service, "run_check", check)
    monkeypatch.setattr(service, "claude", lambda key: None)
    app = make_app(holdings=[dict(h) for h in H[:1]], criteria=[dict(C1), dict(C2)], workspaces=[{"user_id": "u1", "mode": "ai"}])
    app.session_state["screening-section"] = "monitoring"
    app.switch_page("views/screening.py").run()
    next(b for b in app.button if b.label == "Run now").click().run()
    finish(app)
    assert calls == [["c1", "c2"], ["c2"]]
    run = app.session_state["screening_run"]
    assert (run["done"], run["total"], run["errors"]) == (2, 2, [])
    assert [c["criterion"] for c in run["checks"]] == ["Military", "Child labour"]


def test_criterion_missing_twice_is_a_failure_with_retry(make_app, monkeypatch):
    def check(sb, client, company, criteria, **k):
        covered = [c for c in criteria if c["id"] == "c1"]      # Child labour is never covered
        if not covered:
            raise screening.ScreeningError("The AI answer did not cover any criterion. Nothing was saved.")
        r = result_for(company, covered, scores={c["id"]: {"controversy": {"level": "none"}} for c in covered})
        r.missing = [c for c in criteria if c not in covered]
        return r
    monkeypatch.setattr(service, "run_check", check)
    monkeypatch.setattr(service, "claude", lambda key: None)
    app = make_app(holdings=[dict(h) for h in H[:1]], criteria=[dict(C1), dict(C2)], workspaces=[{"user_id": "u1", "mode": "ai"}])
    app.session_state["screening-section"] = "monitoring"
    app.switch_page("views/screening.py").run()
    next(b for b in app.button if b.label == "Run now").click().run()
    finish(app)
    run = app.session_state["screening_run"]
    assert [c["criterion"] for c in run["checks"]] == ["Military", "Child labour"]
    assert run["checks"][1]["error"] == "The AI answer did not cover any criterion. Nothing was saved."
    # A retry is allowed although Run now was used today.
    assert app.session_state["_supabase"].monitor["run_today"]
    retry = next(b for b in app.button if b.label == "Retry failed checks (1)")
    assert not retry.disabled
