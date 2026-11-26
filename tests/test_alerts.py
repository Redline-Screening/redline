"""Alerts: monitoring results and provider incidents, one card per company."""
from test_screening import stored

from redline import alerts as al
from redline import summary as sm
from redline import ui

H = [{"id": "h1", "name": "Meta Platforms", "ticker": "META", "weight": 6, "type": "holding", "monitored": True},
     {"id": "h2", "name": "Logitech", "ticker": "LOGN", "weight": 3, "type": "holding", "monitored": True},
     {"id": "h3", "name": "SAP", "ticker": "SAP", "weight": 5, "type": "holding"}]
MIL = {"id": "c1", "key": "military", "label": "Military", "type": "both", "threshold": 0, "watch_at": 50,
       "controversy_limit": "high", "active": True, "sort": 1}
CHILD = {**MIL, "id": "c2", "key": "child-labour", "label": "Child labour", "type": "conduct", "threshold": None}
F = stored(holding_id="h1", criterion_id="c1", severity="high")


def score(h, c, level, checked="2026-11-26", new=False, **k):
    return {"holding_id": h, "criterion_id": c, "controversy": {"level": level}, "monitor_checked": checked, "monitor_new": new, **k}


RR = {"id": "r1", "title": "Sample incident", "date": "2026-11-20", "severity": "medium", "tickers": ["LOGN"], "criteria": [],
      "url": "https://example.com/s", "origin": "reprisk", "source": "RepRisk", "status": "new"}
MANUAL = {**RR, "id": "m1", "origin": "web", "tickers": ["SAP"], "title": "Manual screening alert"}


def view(scores, alerts=()):
    return al.monitoring_view(H, [MIL, CHILD], {(s["holding_id"], s["criterion_id"]): s for s in scores}, [F], list(alerts))


def test_cards_per_company():
    v = view([score("h1", "c1", "high", new=True), score("h1", "c2", "medium"), score("h3", "c1", "high", checked=None)], [RR, MANUAL])
    assert [c["company"]["name"] for c in v["breach"]] == ["Meta Platforms"]
    assert [x["criterion"]["label"] for x in v["breach"][0]["lines"]] == ["Military"]
    assert v["breach"][0]["new"] and v["breach"][0]["lines"][0]["findings"] == 1
    assert [c["company"]["name"] for c in v["watch"]] == ["Meta Platforms", "Logitech"]
    assert v["watch"][1]["provider"][0]["title"] == "Sample incident"
    names = {c["company"]["name"] for box in ("breach", "watch") for c in v[box]}
    assert "SAP" not in names                    # manual screening results are not on Alerts


def test_no_results():
    assert not view([score("h1", "c1", "high", checked=None)], [MANUAL])["has_results"]


def test_filters():
    v = view([score("h1", "c1", "high"), score("h1", "c2", "medium")], [RR])
    assert [c["company"]["id"] for c in al.select(v["watch"], companies=["h2"])] == ["h2"]
    assert [c["company"]["id"] for c in al.select(v["watch"], criteria=["c2"])] == ["h1"]


def tables(**k):
    return dict(holdings=[dict(h) for h in H], criteria=[dict(MIL), dict(CHILD)], findings=[dict(F)], **k)


def test_page(make_app):
    s = score("h1", "c1", "high", new=True, summary="Breach because of high-severity incidents. Meta is a supplier.",
              summary_date="2026-11-26")
    s["summary_key"] = sm.state_key(s, [F], MIL)
    app = make_app(**tables(scores=[s], alerts=[RR])).switch_page("views/alerts.py").run()
    assert not app.exception
    assert [x.value for x in app.subheader] == ["Breaches", "Watch"]
    shown = [t.value for t in app.text]
    assert "Breach because of high-severity incidents. Meta is a supplier." in shown and "Sample incident" in shown
    assert any("New since the last monitoring run" in c.value for c in app.caption)
    assert [b.label for b in app.button].count("Company profile") == 2
    next(b for b in app.button if b.key == "profile-breach-0").click().run()
    assert app.session_state[ui.COMPANY_KEY] == "h1"


def test_empty_page_links_to_monitoring(make_app):
    app = make_app(**tables()).switch_page("views/alerts.py").run()
    assert "No monitoring results yet." in [m.value for m in app.markdown]
    next(b for b in app.button if b.label == "Open Portfolio Monitoring").click().run()
    assert app.session_state["screening-section"] == "monitoring"


def test_overview_figure(make_app):
    app = make_app(**tables(scores=[score("h1", "c1", "high")]))
    assert app.metric[2].label == "Monitoring: companies in breach" and app.metric[2].value == "1"
