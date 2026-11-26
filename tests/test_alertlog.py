"""Dated alert log and Excel export."""
import io
from datetime import date

import pytest
from conftest import page_title
from openpyxl import load_workbook
from test_screening import stored

from redline import alertlog as al
from redline import service

H = [{"id": "h1", "name": "Meta Platforms", "ticker": "META", "isin": "US30303M1027", "weight": 6, "type": "holding", "monitored": True},
     {"id": "h2", "name": "Logitech", "ticker": "LOGN", "isin": "CH0025751329", "weight": 3, "type": "holding", "monitored": True}]
MIL = {"id": "c1", "key": "military", "label": "Military", "type": "both", "threshold": 0, "watch_at": 50,
       "controversy_limit": "high", "active": True, "sort": 1}
CHILD = {**MIL, "id": "c2", "key": "child-labour", "label": "Child labour", "type": "conduct", "threshold": None}
F = stored(holding_id="h1", criterion_id="c1", severity="high", sources=[{"url": "https://news.example/a", "title": "A"},
                                                                        {"url": "https://news.example/b", "title": "B"}])
TODAY = date(2026, 11, 27)


def entry(day, holding="h1", criterion="c1", status="breach", change="New", **k):
    issuer = {"h1": "Meta Platforms", "h2": "Logitech"}[holding]
    label = {"c1": "Military", "c2": "Child labour", None: None}[criterion]
    return {"id": f"{day}{holding}{criterion}", "day": day, "origin": "monitoring", "holding_id": holding, "criterion_id": criterion,
            "issuer": issuer, "isin": None, "criterion": label, "status": status, "change": change, "severity": "high",
            "summary": f"Summary {day}", "sources": [{"url": "https://news.example/a", "title": "A"}], **k}


LOG = [entry("2026-11-27"), entry("2026-11-27", criterion="c2", status="watch", change="Unchanged"),
       entry("2026-11-26", status="watch"), entry("2026-11-20", holding="h2", status="watch"),
       entry("2026-10-01", holding="h2")]


def test_change():
    assert al.change(None, "breach") == "New"
    assert al.change("watch", "breach") == "Watch → Breach"
    assert al.change("breach", "breach") == "Unchanged"


def test_monitoring_rows():
    scores = {"c1": {"controversy": {"level": "high"}, "summary": "Breach because of high-severity incidents."},
              "c2": {"controversy": {"level": "none"}, "exposure": None}}
    rows = al.monitoring_rows(H[0], [MIL, CHILD], scores, [F], {"c1": "watch"}, TODAY)
    assert len(rows) == 1                      # Child labour is clear and is not logged
    r = rows[0]
    assert (r["day"], r["status"], r["change"], r["severity"], r["isin"]) == ("2026-11-27", "breach", "Watch → Breach", "high", "US30303M1027")
    assert [s["url"] for s in r["sources"]] == ["https://news.example/a", "https://news.example/b"]


def test_periods_and_filters():
    first, last = al.period("7", today_=TODAY)
    assert (first, [r["day"] for r in al.select(LOG, first, last)]) == (date(2026, 11, 21), ["2026-11-27", "2026-11-27", "2026-11-26"])
    first, last = al.period("30", today_=TODAY)
    assert len(al.select(LOG, first, last)) == 4
    assert len(al.select(LOG, date(2026, 10, 1), date(2026, 10, 1))) == 1
    assert [r["holding_id"] for r in al.select(LOG, date(2026, 1, 1), TODAY, companies=["h2"])] == ["h2", "h2"]
    assert len(al.select(LOG, date(2026, 1, 1), TODAY, criteria=["c2"])) == 1


def test_grouping_by_day():
    days = al.by_day(al.select(LOG, date(2026, 11, 20), TODAY))
    assert [d for d, _ in days] == ["2026-11-27", "2026-11-26", "2026-11-20"]
    assert [al.day_label(d, TODAY) for d, _ in days] == ["Today", "Yesterday", "20 Nov 2026"]
    boxes = days[0][1]
    assert [c["issuer"] for c in boxes["breach"]] == ["Meta Platforms"] and len(boxes["breach"][0]["entries"]) == 2
    assert [c["issuer"] for c in days[2][1]["watch"]] == ["Logitech"]


def test_export():
    data = al.to_xlsx(al.select(LOG, date(2026, 11, 20), TODAY))
    ws = load_workbook(io.BytesIO(data)).active
    assert [c.value for c in ws[1]] == al.COLUMNS and all(c.font.bold for c in ws[1])
    assert ws.max_row == 5
    assert ws["B2"].value == "Logitech" and ws["E2"].value == "Watch" and ws["L2"].value == "Portfolio Monitoring"
    assert ws["I2"].hyperlink.target == "https://news.example/a"
    assert ws.column_dimensions["H"].width == 70


def test_provider_rows():
    alert = {"id": "a1", "title": "Sample incident", "date": "2026-11-20", "severity": "medium", "tickers": ["LOGN"],
             "criteria": ["c2"], "url": "https://example.com/s", "origin": "reprisk"}
    r = al.provider_rows([alert], H, [MIL, CHILD], TODAY)[0]
    assert (r["status"], r["origin"], r["criterion"], r["provider_alert_id"]) == ("provider", "provider", "Child labour", "a1")


def test_log_keeps_earlier_days_and_replaces_today(make_app, monkeypatch):
    monkeypatch.setattr(al, "today", lambda: TODAY)
    old = entry("2026-11-26", status="watch")
    stale_today = entry("2026-11-27", status="watch", change="Watch")
    client = make_app(scores=[{"holding_id": "h1", "criterion_id": "c1", "controversy": {"level": "high"}}],
                      findings=[dict(F)], alert_log=[old, stale_today]).session_state["_supabase"]
    service.log_monitoring(client, H[0], [MIL])
    rows = client.tables["alert_log"]
    assert [(r["day"], r["status"], r["change"]) for r in rows] == [("2026-11-26", "watch", "New"), ("2026-11-27", "breach", "Watch → Breach")]


def test_page(make_app, monkeypatch):
    monkeypatch.setattr(al, "today", lambda: TODAY)
    app = make_app(holdings=[dict(h) for h in H], criteria=[dict(MIL), dict(CHILD)], alert_log=[dict(r) for r in LOG])
    app.switch_page("views/alerts.py").run()
    assert not app.exception and page_title(app) == "Alerts"
    assert [s.value for s in app.subheader] == ["Today", "Yesterday"]
    shown = [t.value for t in app.text]
    assert "Summary 2026-11-27" in shown and "Summary 2026-10-01" not in shown
    assert any("blue-badge[New]" in m.value for m in app.markdown)
    assert app.get("download_button")[0].proto.label == "Download log"
    app.segmented_control[0].set_value("30").run()
    assert len(app.subheader) == 3
    app.multiselect[0].select("h2").run()
    assert [s.value for s in app.subheader] == ["20 Nov 2026"]


def test_existing_results_are_entered_once(make_app, monkeypatch):
    monkeypatch.setattr(al, "today", lambda: TODAY)
    score = {"holding_id": "h1", "criterion_id": "c1", "controversy": {"level": "high"}, "monitor_checked": "2026-11-25"}
    app = make_app(holdings=[dict(h) for h in H], criteria=[dict(MIL)], scores=[score], findings=[dict(F)])
    app.switch_page("views/alerts.py").run()
    log = app.session_state["_supabase"].tables["alert_log"]
    assert [(r["day"], r["status"]) for r in log] == [("2026-11-25", "breach")]
    app.run()
    assert len(app.session_state["_supabase"].tables["alert_log"]) == 1


def test_empty(make_app):
    app = make_app(holdings=[dict(h) for h in H], criteria=[dict(MIL)]).switch_page("views/alerts.py").run()
    assert "No monitoring results yet." in [m.value for m in app.markdown]
