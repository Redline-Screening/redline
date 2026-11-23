from redline import alerts as al

H = [{"id": "h1", "name": "Meta Platforms", "ticker": "META", "weight": 6, "type": "holding"},
     {"id": "h2", "name": "Logitech", "ticker": "LOGN", "weight": 3, "type": "holding"}]
C = [{"id": "c1", "label": "Military", "active": True, "sort": 1}]


def finding(i="f1", **k):
    return {"id": i, "holding_id": "h1", "criterion_id": "c1", "category": "contract", "title": "T", "summary": "S",
            "date": "2025-05-29", "date_type": "event", "severity": "high", "status": "open", "last_seen": "2026-11-25",
            "sources": [{"url": "https://a.example/1", "title": "x"}, {"url": "https://b.example/2", "title": "y"}], **k}


def alert(i="a1", **k):
    return {"id": i, "finding_id": "f1", "title": "Title *x*", "summary": "S [a](b)", "date": "2025-05-29", "severity": "high",
            "tickers": ["META"], "criteria": ["c1"], "url": "https://a.example/1", "source": "AI web search", "status": "new", **k}


PROVIDER = alert("a2", finding_id=None, title="Incident", summary=None, date="2026-11-20", tickers=["LOGN"], criteria=[],
                 url="https://example.com/s", source="RepRisk", severity="medium")


def test_join():
    out = al.join([alert(), PROVIDER, alert("a3", finding_id=None, date=None, tickers=["XX"], url="javascript:1")], [finding()], H, C)
    assert [e["id"] for e in out] == ["a2", "a1", "a3"]
    assert out[1]["companies"] == ["Meta Platforms"] and len(out[1]["sources"]) == 2 and out[1]["date_type"] == "event"
    assert out[0]["companies"] == ["Logitech"] and out[0]["sources"] == [{"url": "https://example.com/s"}]
    assert out[2]["companies"] == ["XX"] and out[2]["sources"] == []


def test_filters():
    e = al.join([alert(), PROVIDER, alert("a3", status="dismissed")], [finding()], H, C)
    assert len(al.select(e)) == 2 and len(al.select(e, open_only=False)) == 3
    assert [x["id"] for x in al.select(e, severities=["medium"])] == ["a2"]
    assert [x["id"] for x in al.select(e, companies=["Meta Platforms"])] == ["a1"]
    assert [x["id"] for x in al.select(e, criteria=["c1"])] == ["a1"]


def test_page(make_app):
    many = [alert(f"m{i}", finding_id=None) for i in range(22)]
    app = make_app(holdings=H, criteria=C, findings=[finding()], alerts=[alert(), PROVIDER, *many])
    app.switch_page("views/alerts.py").run()
    assert not app.exception
    assert [m.value for m in app.metric] == ["24", "23", "2"]
    assert "Title *x*" in [t.value for t in app.text]
    next(b for b in app.button if b.label == "Show more").click().run()
    assert not app.exception and sum(t.value == "Title *x*" for t in app.text) == 23
    app.multiselect[0].select("medium").run()
    assert [t.value for t in app.text if t.value in ("Title *x*", "Incident")] == ["Incident"]
    app.multiselect[0].unselect("medium").run()
    app.multiselect[1].select("Meta Platforms").run()
    assert any("Event" in c.value and "2025-05-29" in c.value for c in app.caption)
