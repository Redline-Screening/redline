import pytest
from test_screening import CHILD, MIL, TODAY, URL, Fake, SB, answer, finding, reply, run, search, stored, text

from redline import evidence as ev
from redline import rules, screening, service


@pytest.mark.parametrize("who,proof,legal,limit", [
    ("company", "proven", "none", "severe"), ("company", "proven", "against", "severe"), ("company", "alleged", "against", "severe"),
    ("company", "alleged", "none", "high"), ("company", "alleged", "open", "high"), ("company", "proven", "open", "high"),
    ("company", "alleged", "settled", "medium"), ("company", "proven", "settled", "severe"),
    ("supplier", "proven", "none", "high"), ("supplier", "alleged", "open", "medium"),
    ("partner", "proven", "none", "high"), ("partner", "alleged", "none", "medium"),
    ("unclear", "proven", "none", "medium"), ("company", "proven", "dismissed", "low"), ("supplier", "alleged", "dismissed", "low"),
    (None, None, None, "medium"),
])
def test_max_severity(who, proof, legal, limit):
    assert ev.max_severity(who, proof, legal) == limit


def go(*items, known=(), crit=MIL, **k):
    return run(Fake(reply(search(URL, "https://www.washingtonpost.com/x"), text(answer(*items, cid=crit["id"])))), criteria=[crit], known=known, **k)


def test_new_findings_are_capped_and_missing_classes_are_strict():
    r = go(finding(severity="severe", involvement="supplier", evidence="alleged"), finding(title="B", severity="severe", involvement="x", evidence=None),
           finding(title="C", severity="high", legal_status="dismissed"), finding(title="D", severity="low"))
    assert [f["severity"] for f in r.new] == ["medium", "medium", "low", "low"]
    assert len(r.alerts) == 2


def test_supplier_allegation_is_watch_for_child_labour():
    r = go(finding(severity="severe", involvement="supplier", evidence="alleged"), crit=CHILD)
    c = {**CHILD, "key": "child-labour", "controversy_limit": "high", "watch_at": 50}
    assert rules.evaluate({"controversy": r.scores["c2"]["controversy"]}, c)["state"] == "watch"


def test_recheck_lowers_only_with_an_established_class():
    item = finding(known_id="F1", severity="high", involvement="company", evidence="alleged", legal_status="dismissed")
    r = go(item, known=[stored(severity="high")])
    assert r.updated[0]["severity"] == "low" and r.scores["c1"]["controversy"]["level"] == "low" and not r.alerts
    unclear = finding(known_id="F1", involvement="unclear", evidence="alleged", legal_status="unclear")
    assert go(unclear, known=[stored(severity="high")]).updated[0]["severity"] == "high"
    assert go(known=[stored(severity="high")]).scores["c1"]["controversy"]["level"] == "high"
    # An AI opinion alone does not lower the severity.
    assert go(finding(known_id="F1", severity="low"), known=[stored(severity="high")]).updated[0]["severity"] == "high"


def test_known_classes_are_kept():
    old = stored(severity="medium", involvement="supplier", evidence="alleged", legal_status="open")
    f = go(finding(known_id="F1", involvement="unclear", legal_status="none", severity="severe"), known=[old]).updated[0]
    assert (f["involvement"], f["legal_status"], f["severity"]) == ("supplier", "open", "medium")


def test_lowered_finding_closes_its_alert():
    sb = SB({"id": "t"})
    service.save_result(sb, {"id": "h1", "name": "M"}, screening.Result(updated=[stored(severity="low")]))
    updates = [c[1] for c in sb.calls if c[0] == "alerts:update"]
    assert updates[0]["severity"] == "low" and updates[1] == {"status": "reviewed"}


# Revenue
SHARE = {"kind": "stated_share", "quote": "defence accounts for 0.2% of revenue", "urls": [URL]}
CALC = {"kind": "calculated", "quote": "segment revenue of $200 million", "urls": [URL], "activity_revenue": 200, "total_revenue": 100000,
        "activity_year": 2025, "total_year": 2025}


@pytest.mark.parametrize("source,sourced", [
    (SHARE, True), (CALC, True), (None, False), ({**SHARE, "kind": "none"}, False), ({**SHARE, "urls": ["https://fake.example/x"]}, False),
    ({**SHARE, "quote": "a small part of revenue"}, False), ({**SHARE, "quote": "about 5% of revenue"}, False),
    ({**CALC, "total_year": 2024}, False), ({**CALC, "total_revenue": 1000}, False), ({**CALC, "total_revenue": 0}, False),
    ({**CALC, "activity_year": None, "total_year": None}, False), ({**CALC, "quote": "much"}, False),
])
def test_sourced_estimates(source, sourced):
    out = go(*[], **{}) if False else run(Fake(reply(search(URL), text(answer(exposure_source=source)))))
    s = out.scores["c1"]
    assert s["exposure_sourced"] is sourced and bool(s["exposure_sources"]) is sourced
    assert rules.evaluate(s, MIL)["state"] == ("breach" if sourced else "watch")
    assert rules.revenue_source(s) == ("AI estimate, sourced" if sourced else "Unsourced estimate")


def test_unsourced_rules():
    s = {"exposure": 5, "exposure_kind": "ai_web"}
    assert rules.evaluate(s, MIL) == {"state": "watch", "reasons": ["Unsourced estimate"]}
    assert rules.evaluate({**s, "exposure": 0}, MIL)["state"] == "clear"
    assert rules.evaluate({**s, "controversy": {"level": "high"}}, MIL) == {"state": "breach", "reasons": ["Controversy"]}
    assert rules.evaluate({**s, "exposure_kind": "provider"}, MIL)["state"] == "breach"
    assert rules.revenue_source({"exposure": 5, "exposure_kind": "analyst", "source": "Analyst"}) == "Analyst"


def test_quick_estimate_is_unsourced():
    r = run(Fake(reply(text(answer(exposure_source=SHARE)), s=0)), web=False)
    assert r.scores["c1"]["exposure_sourced"] is False


def test_sourced_figure_is_not_replaced_by_unsourced():
    old = {"exposure": 1, "exposure_kind": "ai_web", "exposure_sourced": True}
    r = run(Fake(reply(search(URL), text(answer()))), scores={"c1": old})
    assert "exposure" not in r.scores["c1"]


def test_numbers():
    assert ev._numbers("1,234.5 and 0,2 and 3.5% of 1,000") == [1234.5, 0.2, 3.5, 1000]


# Outlets
def test_unlinked_outlet_sentence_is_removed():
    r = go(finding(summary="Maven used in operations, says the Army. The Washington Post reported more. It continues."))
    assert r.new[0]["summary"] == "Maven used in operations, says the Army. It continues."
    r = go(finding(summary="The Washington Post reported more.", urls=[URL, "https://www.washingtonpost.com/x"]))
    assert r.new[0]["summary"] == "The Washington Post reported more."


def test_finding_is_left_out_when_nothing_remains():
    r = go(finding(summary="Reuters reported it."), finding(title="Reuters: deal", summary="Fine."))
    assert not r.new and r.left_out == 2


def test_known_text_is_corrected():
    old = stored(title="Maven", summary="Used in Iran, per the Washington Post.")
    f = go(finding(known_id="F1", title="Maven", summary="Used by the Army."), known=[old]).updated[0]
    assert f["summary"] == "Used by the Army."


def test_sentences_keep_abbreviations():
    s = "The U.S. Army signed with Acme Inc. Reuters said so. Done in Sept. 2025."
    assert ev.clean_text("T", s, [{"url": URL}]) is not None
    assert ev.clean_text("T", "The U.S. Army signed. Reuters said so. Done in Sept. 2025.", [{"url": URL}])[1] == "The U.S. Army signed. Done in Sept. 2025."


# Dates
@pytest.mark.parametrize("value,result", [
    ("2026-09-03", ("2026-09-03", "day")), ("2026-09", ("2026-09-01", "month")), ("2025", ("2025-01-01", "year")),
    ("2026-12", None), ("2027", None), ("2026-13", None), ("2026-02-30", None), (None, None), ("Sept 2026", None),
])
def test_dates(value, result):
    assert ev.parse_date(value, TODAY) == result


def test_report_month_from_summary():
    f = go(finding(date=None, date_type="reported", summary="Delivered, per a Sept 2026 report.")).new[0]
    assert (f["date"], f["date_precision"], f["date_type"]) == ("2026-09-01", "month", "reported")
    from redline import ui
    assert ui.finding_date(f) == "Reported: 2026-09"
    assert go(finding(date=None, summary="Signed in March 2024.")).new[0]["date"] is None
    assert ev.reported_month("a May 2025 report and a June 2025 report", TODAY) is None


def test_finer_date_replaces_coarser():
    old = stored(date="2026-09-01", date_precision="month", date_type="reported")
    f = go(finding(known_id="F1", date="2026-09-14", date_type="reported"), known=[old]).updated[0]
    assert (f["date"], f["date_precision"]) == ("2026-09-14", "day")
    f = go(finding(known_id="F1", date="2026", date_type="reported"), known=[f]).updated[0]
    assert f["date_precision"] == "day"


def test_since_with_month():
    r = go(finding(title="Old one", date="2026-10"), finding(title="Same month", date="2026-11"), since="2026-11-15")
    assert [f["title"] for f in r.new] == ["Same month"]


# Dismissing
def test_dismiss(make_app):
    other = stored(id="f2", severity="low", status="open")
    score = {"holding_id": "h1", "criterion_id": "c1", "controversy": {"level": "high", "checked": TODAY}}
    tables = {"findings": [stored(severity="high"), other], "scores": [score], "alerts": [{"id": "a", "finding_id": "f1", "status": "new", "date": None}]}
    client = make_app(**tables).session_state["_supabase"]
    service.dismiss(client, dict(tables["findings"][0]))
    assert tables["findings"][0]["status"] == "dismissed" and tables["alerts"][0]["status"] == "dismissed"
    assert score["controversy"] == {"level": "low", "count": 1, "last": None, "checked": TODAY}


def test_page_shows_classes_and_quote(make_app):
    c = {**MIL, "active": True, "sort": 1, "watch_at": 50, "controversy_limit": "high"}
    f = stored(involvement="supplier", evidence="alleged", legal_status="dismissed", holding_id="h1")
    s = {"holding_id": "h1", "criterion_id": "c1", "exposure": 0.2, "exposure_kind": "ai_web", "exposure_sourced": True,
         "exposure_sources": [{"url": URL, "title": "t"}], "exposure_quote": "0.2% of revenue", "basis": "b"}
    app = make_app(holdings=[{"id": "h1", "name": "Meta", "weight": 6, "type": "holding"}], criteria=[c], findings=[f, stored(id="f2", holding_id="h1")],
                   scores=[s], workspaces=[{"user_id": "u1", "mode": "ai"}]).switch_page("views/screening.py").run()
    assert not app.exception
    captions = " ".join(x.value.replace("\\", "") for x in app.caption)
    for part in ("Supplier of the company", "Alleged", "Case dismissed", "Not classified", "AI estimate, sourced", "Findings not classified: 1"):
        assert part in captions
    assert "Quote: 0.2% of revenue" in [t.value for t in app.text]
    next(b for b in app.button if b.label == "Dismiss").click().run()
    assert not app.exception and any(b.key == "confirm-dismiss" for b in app.button)


def test_allegation_sentence_must_survive():
    # A new finding whose first sentence names an unlinked outlet is left out, not shortened to the denial.
    r = go(finding(summary="The Washington Post reported Maven was used to select targets. Palantir denied it. An inquiry is open."))
    assert not r.new and r.left_out == 1


def test_known_finding_keeps_the_allegation():
    old = stored(title="Maven", summary="Soldiers allege Maven selected targets. Palantir denied it.")
    bad = finding(known_id="F1", title="Maven", summary="The Washington Post says Maven selected targets. Palantir denied it.")
    assert go(bad, known=[old]).updated[0]["summary"] == "Soldiers allege Maven selected targets. Palantir denied it."
    good = finding(known_id="F1", title="Maven", summary="Army documents allege Maven selected targets. An inquiry is open.")
    assert go(good, known=[old]).updated[0]["summary"] == "Army documents allege Maven selected targets. An inquiry is open."


def test_prompt_asks_for_the_allegation_first():
    from redline import screening as sc
    assert "what exactly is alleged and by whom" in sc.build_prompt({"name": "X"}, [MIL], {}, {}, web=True)
