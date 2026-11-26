"""Holding Screening as a first-time user: one check with findings, one without, one failed."""
import time

import pytest
from test_runner import C1, result_for
from test_screening import stored

from redline import screening, service, ui

H = [{"id": "h1", "name": "Palantir Technologies", "weight": 9, "type": "holding"},
     {"id": "h2", "name": "Microsoft", "weight": 5, "type": "holding"},
     {"id": "h3", "name": "Amazon", "weight": 1, "type": "holding"}]
EARLIER = stored(id="old", holding_id="h1", criterion_id="c1", title="Earlier finding", severity="medium")
NEW = stored(id="n1", holding_id="h1", criterion_id="c1", title="Contract finding from this run", severity="high",
             involvement="company", evidence="proven", legal_status="none")
ERROR = "The AI answer was incomplete (output limit reached). Nothing was saved."
INACTIVE = {**C1, "id": "c9", "key": "x", "label": "Gambling", "active": False}


@pytest.fixture
def app(make_app, monkeypatch):
    seen = []

    def check(sb, client, company, criteria, **k):
        seen.append((company["id"], criteria[0]["label"]))
        time.sleep(0.02)
        if company["id"] == "h3":
            raise screening.ScreeningError(ERROR)
        found = company["id"] == "h1"
        if found:
            sb.tables["findings"].append(dict(NEW))
        scores = {criteria[0]["id"]: {"controversy": {"level": "high" if found else "none"}}}
        if found:
            scores[criteria[0]["id"]] |= {"exposure": 0.5, "exposure_kind": "ai_web"}
        return result_for(company, criteria, new=[NEW] if found else [], scores=scores)
    monkeypatch.setattr(service, "run_check", check)
    monkeypatch.setattr(service, "claude", lambda key: None)
    a = make_app(holdings=[dict(h) for h in H], criteria=[dict(C1), dict(INACTIVE)], findings=[dict(EARLIER)],
                 workspaces=[{"user_id": "u1", "mode": "ai"}]).switch_page("views/screening.py").run()
    a.seen = seen
    return a


def texts(app):
    return [t.value for t in app.text] + [m.value for m in app.markdown] + [c.value for c in app.caption]


def finish(app):
    for _ in range(20):
        time.sleep(0.03)
        app.run()
        assert not app.exception
        run = app.session_state["screening_run"]
        if not run["active"] and not run["current"]:
            app.run()
            return


def test_first_run(app):
    assert [s.value for s in app.subheader] == ["Holding Screening"]
    assert "Select at least one company and one criterion." in texts(app)
    app.multiselect[0].select("h1").select("h2").select("h3").run()
    assert "This will run 3 checks. 15 remaining today." in texts(app)
    assert [b.label for b in app.button if b.proto.type == "primary"] == ["Run screening"]
    next(b for b in app.button if b.label == "Run screening").click().run()
    assert "Holding Screening" not in [s.value for s in app.subheader]
    finish(app)

    assert app.multiselect[0].value == ["h1", "h2", "h3"]        # the selection is kept after the run
    shown = texts(app)
    assert app.warning[0].value == "Checks completed: 2 of 3. Failed: 1. New findings: 1."
    labels = [e.label for e in app.expander]
    assert labels[0] == "Results table"
    assert labels[1].startswith("**Palantir Technologies** · :red-badge[Military: Breach] · 1 new, 0 updated")
    assert labels[2].startswith("**Microsoft** · :green-badge[Military: Clear] · no incidents found")
    assert labels[3].startswith("**Amazon** · :red-badge[Check failed]")
    assert not any(e.proto.expanded for e in app.expander)
    table = app.dataframe[0].value
    assert list(table["Change"]) == ["Not screened \u2192 Breach", "Not screened \u2192 Clear", ""]
    assert list(table["Status"]) == ["Breach", "Clear", "Failed"]
    assert table["Revenue %"][0] == 0.5
    assert table["Revenue source"][0] == "Unsourced estimate"
    assert "Contract finding from this run" in shown and "Earlier finding" not in shown
    assert "No incidents found for Microsoft / Military." in shown
    assert f"Check failed: {ERROR}" in shown
    assert any("blue-badge[New]" in m.value for m in app.markdown)
    assert any(b.label == "Retry failed checks (1)" for b in app.button)
    links = [b.label for b in app.button if b.label.startswith("View all findings")]
    assert links == ["View all findings for Palantir Technologies", "View all findings for Microsoft", "View all findings for Amazon"]
    next(b for b in app.button if b.label == "View all findings for Palantir Technologies").click().run()
    assert app.session_state[ui.COMPANY_KEY] == "h1"
    app.switch_page("views/screening.py").run()
    next(b for b in app.button if b.label == "Retry failed checks (1)").click().run()
    finish(app)
    assert app.seen[-1] == ("h3", "Military")


def test_inactive_and_standard_criteria(app):
    app.multiselect[0].select("h2").run()
    app.multiselect[1].select("c9").select("template:tobacco").run()
    assert "This will run 3 checks. 15 remaining today." in texts(app)
    assert any("added as inactive criteria" in c.value for c in app.caption)
    next(b for b in app.button if b.label == "Run screening").click().run()
    finish(app)
    added = [c for c in app.session_state["_supabase"].tables["criteria"] if c.get("key") == "tobacco"]
    assert len(added) == 1 and added[0]["active"] is False
    assert sorted(label for _, label in app.seen) == ["Gambling", "Military", "Tobacco"]


def test_clear_results(app):
    app.multiselect[0].select("h2").run()
    next(b for b in app.button if b.label == "Run screening").click().run()
    finish(app)
    next(b for b in app.button if b.label == "Clear results").click().run()
    assert not app.expander and [s.value for s in app.subheader] == ["Holding Screening"]


def test_leaving_the_page_pauses(make_app, monkeypatch):
    import threading
    gate = threading.Event()

    def check(sb, client, company, criteria, **k):
        gate.wait(5)
        return result_for(company, criteria)
    monkeypatch.setattr(service, "run_check", check)
    monkeypatch.setattr(service, "claude", lambda key: None)
    app = make_app(holdings=[dict(h) for h in H], criteria=[dict(C1)], workspaces=[{"user_id": "u1", "mode": "ai"}])
    app.switch_page("views/screening.py").run()
    app.multiselect[0].select("h1").select("h2").select("h3").run()
    next(b for b in app.button if b.label == "Run screening").click().run()
    app.switch_page("views/overview.py").run()
    gate.set()
    time.sleep(0.1)
    app.switch_page("views/screening.py").run()
    run = app.session_state["screening_run"]
    assert run["done"] == 1 and len(run["jobs"]) == 2 and not run["active"]
    assert any(b.label == "Resume (2 open)" for b in app.button)


def test_unchanged_revenue_is_shown(make_app, monkeypatch):
    monkeypatch.setattr(service, "run_check", lambda sb, client, company, criteria, **k: result_for(
        company, criteria, before={"c1": {"exposure": 40, "exposure_kind": "provider", "source": "MSCI"}},
        scores={"c1": {"controversy": {"level": "none"}}}))
    monkeypatch.setattr(service, "claude", lambda key: None)
    app = make_app(holdings=[dict(h) for h in H], criteria=[dict(C1)], workspaces=[{"user_id": "u1", "mode": "ai"}])
    app.switch_page("views/screening.py").run()
    app.multiselect[0].select("h2").run()
    next(b for b in app.button if b.label == "Run screening").click().run()
    finish(app)
    table = app.dataframe[0].value
    assert table["Revenue %"][0] == 40 and table["Revenue source"][0] == "MSCI"


def test_run_results_start_with_the_summary(make_app, monkeypatch):
    from redline import summary as sm
    crit = dict(C1)

    def check(sb, client, company, criteria, **k):
        score = {"holding_id": company["id"], "criterion_id": "c1", "controversy": {"level": "high"}}
        found = dict(NEW, holding_id=company["id"])
        score.update(summary="Breach because of high-severity incidents. Simulated summary.", summary_date="2026-11-26")
        score["summary_key"] = sm.state_key(score, [found], crit)
        sb.tables.setdefault("scores", []).append(score)
        sb.tables.setdefault("findings", []).append(found)
        return result_for(company, criteria, new=[found], scores={"c1": {"controversy": {"level": "high"}}})
    monkeypatch.setattr(service, "run_check", check)
    monkeypatch.setattr(service, "claude", lambda key: None)
    app = make_app(holdings=[dict(h) for h in H], criteria=[crit], workspaces=[{"user_id": "u1", "mode": "ai"}])
    app.switch_page("views/screening.py").run()
    app.multiselect[0].select("h1").run()
    next(b for b in app.button if b.label == "Run screening").click().run()
    finish(app)
    shown = [t.value for t in app.text]
    assert shown.index("Breach because of high-severity incidents. Simulated summary.") < shown.index("Contract finding from this run")


def test_unexpected_failure_is_listed(make_app, monkeypatch):
    def check(*a, **k):
        raise RuntimeError("database down")
    monkeypatch.setattr(service, "run_check", check)
    monkeypatch.setattr(service, "claude", lambda key: None)
    app = make_app(holdings=[dict(h) for h in H], criteria=[dict(C1)], workspaces=[{"user_id": "u1", "mode": "ai"}])
    app.switch_page("views/screening.py").run()
    app.multiselect[0].select("h1").run()
    next(b for b in app.button if b.label == "Run screening").click().run()
    finish(app)
    assert list(app.dataframe[0].value["Status"]) == ["Failed"]
    assert "Check failed: The result could not be saved." in texts(app)
