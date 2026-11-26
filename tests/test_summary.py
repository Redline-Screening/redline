from types import SimpleNamespace as NS

import pytest
from test_screening import MIL, URL, Fake, answer, finding, reply, run, search, stored, text

from redline import evidence as ev
from redline import summary as sm
from redline import ui

C = {**MIL, "key": "military", "active": True, "sort": 1, "watch_at": 50, "controversy_limit": "high"}
H = {"id": "h1", "name": "Palantir Technologies", "ticker": "PLTR", "weight": 9, "type": "holding"}
F = stored(holding_id="h1", severity="severe", involvement="company", evidence="proven", legal_status="none")
SCORE = {"holding_id": "h1", "criterion_id": "c1", "exposure": 35, "exposure_kind": "ai_web", "controversy": {"level": "severe"}}


class Haiku:
    def __init__(self, text='{"summary": "Breach because of severe incidents. Palantir is a prime defence contractor with proven contracts."}', stop="end_turn"):
        self.text, self.stop, self.calls = text, stop, []
        self.messages = self

    def create(self, **request):
        self.calls.append(request)
        return NS(content=[NS(type="text", text=self.text)], stop_reason=self.stop,
                  usage=NS(input_tokens=800, output_tokens=80, cache_creation_input_tokens=None, cache_read_input_tokens=0))


def client(make_app, can=True, **tables):
    c = make_app(holdings=[dict(H)], criteria=[dict(C)], **tables).session_state["_supabase"]
    calls = []

    def rpc(name, args=None):
        calls.append((name, args))
        return NS(execute=lambda: NS(data=can if name == "can_summarize" else True))
    c.rpc, c.calls = rpc, calls
    return c


def test_generated_after_a_change_and_logged(make_app):
    sb = client(make_app, scores=[dict(SCORE)], findings=[dict(F)])
    haiku = Haiku()
    text_out = sm.refresh(sb, haiku, H, C)
    assert text_out.startswith("Breach because of")
    assert haiku.calls[0]["model"] == "claude-haiku-5-5" and "tools" not in haiku.calls[0]
    prompt = haiku.calls[0]["messages"][0]["content"]
    assert "Unsourced estimate" in prompt and F["title"] in prompt and "Company or subsidiary" in prompt
    assert "caused by: severe incidents" in prompt and "not a cause of a breach" in prompt
    log = dict(sb.calls)["log_ai_summary"]
    assert log["p_cost"] == round((800 * 0.10 + 80 * 0.50) / 1e6, 6)
    row = sb.tables["scores"][0]
    assert sm.is_current(row, sb.tables["findings"], C)
    # Nothing changed: no second call.
    sm.refresh(sb, haiku, H, C)
    assert len(haiku.calls) == 1
    # A dismissed finding changes the basis, so the summary is regenerated.
    sb.tables["findings"][0]["status"] = "dismissed"
    assert not sm.is_current(row, sb.tables["findings"], C)
    sm.refresh(sb, haiku, H, C)
    assert len(haiku.calls) == 2


def test_not_generated_when_clear_or_without_budget(make_app):
    clear = {**SCORE, "exposure": 0, "exposure_kind": "provider", "controversy": {"level": "none"}}
    sb = client(make_app, scores=[clear])
    haiku = Haiku()
    assert sm.refresh(sb, haiku, H, C) is None and not haiku.calls
    sb = client(make_app, can=False, scores=[dict(SCORE)], findings=[dict(F)])
    assert sm.refresh(sb, haiku, H, C) is None and not haiku.calls


@pytest.mark.parametrize("reply_text,stop", [("no json", "end_turn"), ('{"summary": "The article is an image page."}', "end_turn"),
                                             ('{"summary": "x"}', "max_tokens")])
def test_unusable_summaries_are_not_saved(make_app, reply_text, stop):
    sb = client(make_app, scores=[dict(SCORE)], findings=[dict(F)])
    assert sm.refresh(sb, Haiku(reply_text, stop), H, C) is None
    assert "summary" not in sb.tables["scores"][0]


def test_api_problem_does_not_raise(make_app):
    class Broken:
        messages = NS(create=lambda **k: (_ for _ in ()).throw(RuntimeError("down")))
    sb = client(make_app, scores=[dict(SCORE)], findings=[dict(F)])
    assert sm.refresh(sb, Broken(), H, C) is None


def test_profile_shows_summary_or_note(make_app):
    current = {**SCORE, "summary": "Palantir summary text.", "summary_date": "2026-11-26"}
    current["summary_key"] = sm.state_key(current, [F], C)
    app = make_app(holdings=[dict(H)], criteria=[dict(C)], scores=[current], findings=[dict(F)])
    app.session_state[ui.COMPANY_KEY] = "h1"
    app.switch_page("views/company.py").run()
    assert "Palantir summary text." in [t.value for t in app.text]
    assert any(c.value == "Summary from 2026-11-26" for c in app.caption)
    assert app.expander[0].label == "Findings (1)" and not app.expander[0].proto.expanded
    stale = {**current, "summary_key": "old"}
    app = make_app(holdings=[dict(H)], criteria=[dict(C)], scores=[stale], findings=[dict(F)])
    app.session_state[ui.COMPANY_KEY] = "h1"
    app.switch_page("views/company.py").run()
    assert any(c.value == "Summary available after the next check" for c in app.caption)
    assert "Palantir summary text." not in [t.value for t in app.text]


# Sources of one event
def test_amounts():
    assert ev.amounts("$618M Maven deal, $10 billion agreement, EUR 1.2bn and US$480 million") == {618, 10000, 1200, 480}


@pytest.mark.parametrize("title,keep", [
    ("Army awards Palantir $618 million Maven contract", True), ("Palantir wins $10B Army enterprise agreement", False),
    ("Palantir $795M Maven expansion", False), ("Palantir Maven contract grows", True), ("$618.4M Maven deal", True),
])
def test_same_event(title, keep):
    assert ev.same_event("Palantir $618M Maven Smart System contract", title) is keep


def test_finding_keeps_only_matching_sources():
    other = "https://news.example/other"
    item = finding(title="Palantir $618M Maven contract", urls=[URL, other])
    r = run(Fake(reply(NS(type="web_search_tool_result", content=[NS(url=URL, title="Army awards $618M Maven deal"),
                                                                  NS(url=other, title="Palantir $10B Army agreement")]),
                       text(answer(item)))))
    assert [s["url"] for s in r.new[0]["sources"]] == [URL]


def test_finding_without_matching_sources_is_left_out():
    item = finding(title="Palantir $618M Maven contract")
    r = run(Fake(reply(NS(type="web_search_tool_result", content=[NS(url=URL, title="Palantir $480M Army deal")]), text(answer(item)))))
    assert not r.new and r.left_out == 1


def test_profile_generates_missing_summary_once(make_app, monkeypatch):
    from redline import db
    calls = []
    monkeypatch.setattr(db, "refresh_summaries", lambda pairs: calls.append([(h["id"], c["id"]) for h, c in pairs]))
    app = make_app(holdings=[dict(H)], criteria=[dict(C)], scores=[dict(SCORE)], findings=[dict(F)])
    app.session_state[ui.COMPANY_KEY] = "h1"
    app.switch_page("views/company.py").run()
    app.run()
    assert not app.exception and calls == [[("h1", "c1")]]


AMAZON = {"holding_id": "h1", "criterion_id": "c1", "exposure": 1.0, "exposure_kind": "ai_web", "controversy": {"level": "high"}}


def test_drivers_name_the_real_cause():
    assert sm.drivers(AMAZON, C) == ["high-severity incidents"]
    sourced = {**AMAZON, "exposure_sourced": True, "controversy": {"level": "none"}}
    assert sm.drivers(sourced, C) == ["a revenue share of 1.0% from a source, above the limit of 0%"]
    watch = {**AMAZON, "controversy": {"level": "none"}}
    assert sm.drivers(watch, C) == ["an unsourced revenue estimate of 1.0%, above the limit of 0%"]


@pytest.mark.parametrize("summary,ok", [
    ("Breach because of high-severity contract findings. Amazon supplies cloud services to the Pentagon; revenue of 1.0% is an unsourced estimate.", True),
    ("Amazon is in breach of the 0.0% military and defence revenue limit.", False),
    ("Watch because of a supplier allegation.", False),
    ("Breach because of contracts, with the controversy status driven by two findings.", False),
    ("Breach because of " + "very " * 60 + "many findings.", False),
])
def test_acceptable(summary, ok):
    assert sm.acceptable(summary, AMAZON, C) is ok


def test_second_attempt_and_logging(make_app):
    class TwoReplies(Haiku):
        def create(self, **request):
            self.text = '{"summary": "Amazon is in breach of the limit."}' if not self.calls else \
                '{"summary": "Breach because of high-severity incidents. Amazon provides cloud services for military contracts."}'
            return super().create(**request)
    sb = client(make_app, scores=[dict(AMAZON)], findings=[dict(F, severity="high")])
    haiku = TwoReplies()
    assert sm.refresh(sb, haiku, H, C).startswith("Breach because of high-severity incidents")
    assert len(haiku.calls) == 2 and [n for n, _ in sb.calls].count("log_ai_summary") == 2


def test_new_version_regenerates():
    row = {**AMAZON, "summary": "x", "summary_key": sm.state_key(AMAZON, [], C)}
    assert sm.is_current(row, [], C)
    old = sm.VERSION
    try:
        sm.VERSION = "1"
        assert not sm.is_current(row, [], C)
    finally:
        sm.VERSION = old


def test_proven_findings_come_first():
    alleged = stored(id="a", title="Alleged case", severity="high", involvement="company", evidence="alleged", legal_status="open")
    proven = stored(id="p", title="Proven contract", severity="high", involvement="company", evidence="proven", legal_status="none")
    prompt = sm.build_prompt(H, C, SCORE, [alleged, proven])
    assert prompt.index("Proven contract") < prompt.index("Alleged case") and "strongest evidence is a proven finding" in prompt
