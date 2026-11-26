"""Company Profiles, links to them, and the content rules of part 1."""
import pytest
from test_screening import MIL, URL, Fake, answer, finding, reply, run, search, stored, text

from redline import evidence as ev
from redline import ui

H = [{"id": "h1", "name": "Palantir Technologies", "ticker": "PLTR", "weight": 9, "type": "holding"},
     {"id": "h2", "name": "Microsoft", "ticker": "MSFT", "weight": 5, "type": "holding"}]
C = {**MIL, "key": "military", "active": True, "sort": 1, "watch_at": 50, "controversy_limit": "high"}


def make(make_app, **k):
    return make_app(holdings=[dict(h) for h in H], criteria=[dict(C)], **k)


def test_profile_shows_status_findings_and_dates(make_app):
    old = stored(holding_id="h2", title="Supplier case", involvement="indirect", evidence="proven", legal_status="none",
                 first_seen="2026-11-20", last_seen="2026-11-26")
    score = {"holding_id": "h2", "criterion_id": "c1", "exposure": 2, "exposure_kind": "ai_web",
             "controversy": {"level": "medium", "checked": "2026-11-26"}}
    app = make(make_app, findings=[old], scores=[score])
    app.session_state[ui.COMPANY_KEY] = "h2"
    app.switch_page("views/company.py").run()
    assert not app.exception
    assert app.title[0].value == "Company Profile" and app.selectbox[0].value == "h2"
    table = app.dataframe[0].value
    assert list(table["Revenue source"]) == ["Unsourced estimate"] and list(table["Last web check"]) == ["2026-11-26"]
    captions = " ".join(c.value.replace("\\", "") for c in app.caption)
    for part in ("Supplier to the party involved", "Found 2026-11-20", "Last confirmed 2026-11-26", "Last web check: 2026-11-26"):
        assert part in captions
    assert "Supplier case" in [t.value for t in app.text]
    assert [e.label for e in app.expander] == ["Findings (1)", "Analyst Assessment"]


def test_links_from_alerts_and_overview(make_app):
    f = stored(holding_id="h1", severity="high", involvement="company", evidence="proven", legal_status="none")
    monitored = {"holding_id": "h1", "criterion_id": "c1", "controversy": {"level": "high"}, "monitor_checked": "2026-11-26"}
    app = make(make_app, findings=[f], scores=[monitored]).switch_page("views/alerts.py").run()
    next(b for b in app.button if b.label == "Company profile").click().run()
    assert not app.exception
    assert app.session_state[ui.COMPANY_KEY] == "h1"
    app = make(make_app)
    assert any(p.proto.page == "alerts" for p in app.get("page_link"))


@pytest.mark.parametrize("who,proof,limit", [("indirect", "proven", "medium"), ("indirect", "alleged", "low")])
def test_indirect_is_rated_lower(who, proof, limit):
    assert ev.max_severity(who, proof, "none") == limit


def test_indirect_supplier_finding():
    r = run(Fake(reply(search(URL), text(answer(finding(severity="high", involvement="indirect", evidence="proven"))))))
    assert r.new[0]["involvement"] == "indirect" and r.new[0]["severity"] == "medium"


@pytest.mark.parametrize("sentence", [
    "The article is a TechCrunch image page, and the 2016 date is the reporting date.",
    "The source only lists the contract value.",
    "Search results did not confirm the amount.",
    "I could not find the exact date.",
    "The publication date is used.",
])
def test_process_notes_are_removed(sentence):
    summary = f"Microsoft supplies cloud services under the contract. {sentence}"
    assert ev.clean_text("T", summary, [{"url": URL}]) == ("T", "Microsoft supplies cloud services under the contract.")


def test_incident_sentences_are_kept():
    for s in ("The Army awarded the contract in 2025.", "The lawsuit was dismissed in 2024.", "Reports say the page was removed by the company."):
        assert ev.clean_text("T", s, [{"url": URL}]) == ("T", s)


def test_process_note_first_leaves_the_finding_out():
    r = run(Fake(reply(search(URL), text(answer(finding(summary="The article is an image page. A contract was signed."))))))
    assert not r.new and r.left_out == 1


def test_duplicate_links_are_shown_once(make_app):
    f = stored(holding_id="h1", sources=[{"url": "https://breakingdefense.com/a/", "title": "IVAS"},
                                         {"url": "https://www.breakingdefense.com/a", "title": "IVAS"},
                                         {"url": "https://breakingdefense.com/b", "title": "Second IVAS article"}])
    app = make(make_app, findings=[f])
    app.session_state[ui.COMPANY_KEY] = "h1"
    app.switch_page("views/company.py").run()
    labels = [b.proto.label for b in app.get("link_button")]
    assert labels == ["breakingdefense.com\\: IVAS", "breakingdefense.com\\: Second IVAS article"]
