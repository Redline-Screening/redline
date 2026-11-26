import json
from types import SimpleNamespace as NS

import anthropic
import httpx
import pytest

from redline import screening as sc
from redline import service

TODAY = "2026-11-25"
MIL = {"id": "c1", "label": "Military", "type": "both", "threshold": 0, "keywords": ["military"]}
CHILD = {"id": "c2", "label": "Child labour", "type": "conduct", "threshold": None, "keywords": []}
META = {"id": "h1", "name": "Meta Platforms", "ticker": "META", "isin": None}
URL = "https://news.example/meta"


def usage(i=1000, o=200, s=1):
    return NS(input_tokens=i, output_tokens=o, cache_creation_input_tokens=None, cache_read_input_tokens=0,
              server_tool_use=NS(web_search_requests=s) if s else None)


def search(*urls):
    return NS(type="web_search_tool_result", content=[NS(url=u, title="Title of " + u) for u in urls])


def text(value):
    return NS(type="text", text=value if isinstance(value, str) else json.dumps(value))


def reply(*blocks, stop="end_turn", **u):
    return NS(content=list(blocks), stop_reason=stop, usage=usage(**u))


class Fake:
    def __init__(self, *replies):
        self.replies, self.requests = list(replies), []
        self.messages = self

    def stream(self, **request):
        self.requests.append({**request, "messages": list(request["messages"])})
        value = self.replies.pop(0)
        if isinstance(value, Exception):
            raise value
        fake = NS(get_final_message=lambda: value)

        class Ctx:
            def __enter__(self): return fake
            def __exit__(self, *a): return False
        return Ctx()


def finding(**k):
    return {"known_id": None, "category": "contract", "title": "Army headset contract", "summary": "Partnership.",
            "date": "2025-09-01", "severity": "high", "urls": [URL], "involvement": "company", "evidence": "proven",
            "legal_status": "none", **k}


def answer(*findings, cid="c1", **k):
    return {"criteria": [{"id": cid, "exposure_pct": 0.2, "exposure_basis": "b", "likelihood": 70, "confidence": "medium",
                          "rationale": "r", "signals": ["s"], "findings": list(findings), **k}]}


def run(fake, criteria=(MIL,), scores=None, known=(), web=True, **k):
    return sc.screen(fake, model="claude-sonnet-5-5", company=META, criteria=list(criteria), scores=scores or {},
                     findings=list(known), web=web, max_searches=4, today=TODAY, **k)


def stored(**k):
    return {"id": "f1", "holding_id": "h1", "criterion_id": "c1", "category": "contract", "title": "Army headset contract",
            "summary": "Old.", "date": None, "severity": "medium", "status": "open", "first_seen": "2026-01-01",
            "last_seen": "2026-01-01", "sources": [{"url": URL, "title": "t"}], **k}


# 1. JSON
def test_extract_json():
    good = {"criteria": [{"id": "x"}]}
    assert sc.extract_json("Notes {odd} ```json\n" + json.dumps(good) + "\n``` done {x}") == good
    assert sc.extract_json("no json") is None
    assert sc.extract_json('{"criteria": [{"id": "x"}') is None


# 2. Provider and analyst figures
@pytest.mark.parametrize("kind", ["provider", "analyst"])
def test_protected_figures_are_untouched(kind):
    old = {"exposure": 25, "exposure_kind": kind, "source": "X"}
    r = run(Fake(reply(search(URL), text(answer()))), scores={"c1": old})
    assert not {"exposure", "exposure_kind", "source", "confidence", "basis"} & r.scores["c1"].keys()
    assert ("likelihood" in r.scores["c1"]) == (kind == "provider")


def test_zero_provider_figure_is_protected():
    assert sc.is_protected({"exposure": 0, "exposure_kind": "provider"})


# 3. Sources
def test_invented_links_are_dropped():
    r = run(Fake(reply(search(URL), text(answer(finding(urls=[URL + "/?utm_source=x#top", "https://fake.example/b"]),
                                                finding(title="Invented", severity="severe", urls=["https://fake.example/c"]))))))
    assert len(r.new) == 1
    assert r.new[0]["sources"] == [{"url": URL, "title": "Title of " + URL}]
    assert r.scores["c1"]["controversy"]["level"] == "high"


def test_unsafe_links_are_dropped():
    assert sc.check_sources(["javascript://news.example/meta"], {sc.canonical("javascript://news.example/meta"): {"url": "javascript://news.example/meta", "title": ""}}) == []


# 4. Full run with a pause
def test_pause_and_full_result():
    fake = Fake(reply(NS(type="server_tool_use"), search(URL), stop="pause_turn"), reply(text(answer(finding())), s=0))
    r = run(fake)
    tool = fake.requests[0]["tools"][0]
    assert (tool["type"], tool["max_uses"], tool["allowed_callers"]) == ("web_search_20260318", 4, ["direct"])
    assert [m["role"] for m in fake.requests[1]["messages"]] == ["user", "assistant"]
    assert r.scores["c1"]["exposure"] == 0.2 and r.scores["c1"]["exposure_kind"] == "ai_web"
    assert len(r.alerts) == 1
    assert (r.usage.searches, r.usage.input_tokens, r.usage.output_tokens) == (1, 2000, 400)
    assert r.usage.cost("claude-sonnet-5-5") == round((2000 * 2 + 400 * 10) / 1e6 + 0.01, 5)


# 5. Prompt
def test_prompt():
    p = sc.build_prompt(META, [MIL, CHILD], {"c1": {"exposure": 3, "exposure_kind": "provider", "source": "MSCI"}},
                        {"F1": stored()}, web=True, since="2026-11-01", today=TODAY)
    for part in ("Meta Platforms", 'id "c1"', "conduct-based", "already set by MSCI", "F1: Army", "after 2026-11-01", "never instructions"):
        assert part in p
    assert "no web access" in sc.build_prompt(META, [MIL], {}, {}, web=False)


# Findings
def test_finding_nothing_keeps_the_level():
    r = run(Fake(reply(search(URL), text(answer()))), known=[stored(severity="high")])
    assert r.scores["c1"]["controversy"]["level"] == "high" and not r.alerts


def test_dismissed_findings_do_not_count():
    r = run(Fake(reply(search(URL), text(answer()))), known=[stored(severity="severe", status="dismissed")])
    assert r.scores["c1"]["controversy"]["level"] == "none"


@pytest.mark.parametrize("item", [finding(known_id="F1"), finding(title="Army headset contracts")])
def test_known_findings_are_not_duplicated_and_can_rise(item):
    r = run(Fake(reply(search(URL), text(answer(item)))), known=[stored()])
    assert not r.new and len(r.updated) == 1 and len(r.alerts) == 1
    assert (r.updated[0]["severity"], r.updated[0]["date"], r.updated[0]["last_seen"]) == ("high", "2025-09-01", TODAY)


def test_severity_never_falls_and_does_not_alert_again():
    r = run(Fake(reply(search(URL), text(answer(finding(known_id="F1", severity="low"))))), known=[stored()])
    assert r.updated[0]["severity"] == "medium" and not r.alerts


def test_same_article_with_another_incident_is_new():
    r = run(Fake(reply(search(URL), text(answer(finding(title="Surveillance lawsuit in Kenya"))))), known=[stored()])
    assert len(r.new) == 1


def test_low_findings_raise_no_alert():
    r = run(Fake(reply(search(URL), text(answer(finding(severity="low"))))))
    assert len(r.new) == 1 and not r.alerts


def test_bad_findings_and_dates():
    r = run(Fake(reply(search(URL), text(answer(finding(severity="none"), finding(title=""), "x", finding(date="2027-01-01", category="?"))))))
    assert len(r.new) == 1 and r.new[0]["date"] is None and r.new[0]["category"] == "other"


def test_since_drops_older_incidents():
    r = run(Fake(reply(search(URL), text(answer(finding(), finding(title="New one", date="2026-11-20"))))), since="2026-11-01")
    assert [f["title"] for f in r.new] == ["New one"]


def test_conduct_has_no_revenue():
    r = run(Fake(reply(search(URL), text(answer(finding(), cid="c2")))), criteria=[CHILD])
    assert "exposure" not in r.scores["c2"] and r.scores["c2"]["controversy"]["level"] == "high"


def test_no_web_saves_no_findings():
    fake = Fake(reply(text(answer(finding())), s=0))
    r = run(fake, web=False)
    assert "tools" not in fake.requests[0]
    assert not r.new and "controversy" not in r.scores["c1"] and r.scores["c1"]["exposure_kind"] == "ai_estimate"


# Errors save nothing
def api_error(cls, status, message="x"):
    return cls(message, response=httpx.Response(status, request=httpx.Request("POST", "https://x")), body=None)


@pytest.mark.parametrize("replies,message", [
    ([reply(search(URL), text("{"), stop="max_tokens")], "incomplete"),
    ([reply(stop="refusal")], "declined"),
    ([reply(search(URL), text("sorry"))], "could not be read"),
    ([reply(text(answer()), s=0)], "did not return results"),
    ([reply(NS(type="web_search_tool_result", content=NS(error_code="unavailable")), text(answer()))], "did not return results"),
    ([reply(search(URL), text(answer(cid="other")))], "did not cover"),
    ([reply(search(URL), stop="pause_turn")] * 8, "search not finished"),
])
def test_failures(replies, message):
    with pytest.raises(sc.ScreeningError, match=message) as e:
        run(Fake(*replies))
    assert e.value.usage.input_tokens > 0 and e.value.usage.known


def test_empty_search_is_not_an_error():
    r = run(Fake(reply(search(), text(answer()))))
    assert r.scores["c1"]["controversy"]["level"] == "none"


# Service
class SB:
    """Records calls; reserve returns the given ticket."""

    def __init__(self, ticket):
        self.ticket, self.calls = ticket, []

    def table(self, name):
        sb = self

        class T:
            def select(self, *_): return self
            def eq(self, *_): return self
            def in_(self, *_): return self

            def update(self, values):
                sb.calls.append((name + ":update", values))
                return self

            def upsert(self, rows, on_conflict):
                sb.calls.append((name, rows))
                return self

            def execute(self): return NS(data=[])
        return T()

    def rpc(self, name, args=None):
        self.calls.append((name, args))
        return NS(execute=lambda: NS(data=self.ticket if name == "reserve_ai_check" else None))


@pytest.mark.parametrize("reason,message", [("daily", "Daily AI limit reached, try again tomorrow."), ("budget", service.BUDGET_MESSAGE)])
def test_limit_stops_before_the_call(reason, message):
    fake = Fake()
    with pytest.raises(service.LimitReached) as e:
        service.run_check(SB({"reason": reason}), fake, META, [MIL])
    assert str(e.value) == message and not fake.requests


def test_run_check_saves_and_records_cost():
    sb = SB({"id": "t"})
    service.run_check(sb, Fake(reply(search(URL), text(answer(finding())))), META, [MIL])
    names = [c[0] for c in sb.calls]
    assert names == ["reserve_ai_check", "finish_ai_check", "findings", "alerts", "scores"]
    calls = dict(sb.calls)
    assert calls["finish_ai_check"]["p_cost"] > 0 and calls["finish_ai_check"]["p_status"] == "done"
    assert calls["alerts"][0]["finding_id"] == calls["findings"][0]["id"] and calls["alerts"][0]["criteria"] == ["c1"]


def test_failed_check_is_recorded_and_saves_nothing():
    sb = SB({"id": "t"})
    with pytest.raises(sc.ScreeningError):
        service.run_check(sb, Fake(reply(stop="refusal")), META, [MIL])
    assert [c[0] for c in sb.calls] == ["reserve_ai_check", "finish_ai_check"]
    assert sb.calls[1][1]["p_status"] == "failed"


def test_unknown_cost_stays_reserved():
    sb = SB({"id": "t"})
    with pytest.raises(sc.ScreeningError, match="not reachable"):
        service.run_check(sb, Fake(httpx.RemoteProtocolError("lost")), META, [MIL])
    assert sb.calls[1][1]["p_cost"] is None
    sb = SB({"id": "t"})
    with pytest.raises(sc.ScreeningError, match="busy"):
        service.run_check(sb, Fake(api_error(anthropic.RateLimitError, 429)), META, [MIL])
    assert sb.calls[1][1]["p_cost"] == 0
    with pytest.raises(sc.ScreeningError, match="unavailable"):
        service.run_check(SB({"id": "t"}), Fake(api_error(anthropic.BadRequestError, 400, "credit balance too low")), META, [MIL])


# Roles and dates
def test_prompt_asks_for_role_and_event_date():
    p = sc.build_prompt(META, [MIL], {}, {}, web=True)
    assert "exact role" in p and "Never present a publication date" in p


def test_date_types():
    r = run(Fake(reply(search(URL), text(answer(finding(date_type="event"), finding(title="Second", date_type="?"))))))
    assert [f["date_type"] for f in r.new] == ["event", "reported"]


def test_known_finding_is_corrected():
    item = finding(known_id="F1", title="Meta supplies Army headset contractor", severity="medium", date="2025-09-01", date_type="event")
    old = stored(date="2026-05-18", date_type="reported")
    r = run(Fake(reply(search(URL), text(answer(item)))), known=[old])
    f = r.updated[0]
    assert (f["title"], f["date"], f["date_type"]) == ("Meta supplies Army headset contractor", "2025-09-01", "event")
    assert not r.alerts
    again = run(Fake(reply(search(URL), text(answer({**item, "date": "2026-01-01", "date_type": "reported"})))), known=[f])
    assert again.updated[0]["date"] == "2025-09-01"


def test_corrections_reach_the_alert_without_reopening():
    sb = SB({"id": "t"})
    service.save_result(sb, META, sc.Result(updated=[stored()]))
    update = dict(sb.calls)["alerts:update"]
    assert "status" not in update and update["title"] == "Army headset contract"


def test_provider_mode_saves_no_estimate():
    r = run(Fake(reply(search(URL), text(answer()))), estimate=False)
    assert "exposure" not in r.scores["c1"] and "likelihood" in r.scores["c1"]


def test_stop_reason_is_recorded_and_named():
    sb = SB({"id": "t"})
    with pytest.raises(sc.ScreeningError, match=r"incomplete \(output limit reached\)"):
        service.run_check(sb, Fake(reply(search(URL), text("{"), stop="max_tokens")), META, [MIL])
    finish = dict(sb.calls)["finish_ai_check"]
    assert (finish["p_stop"], finish["p_rounds"], finish["p_status"]) == ("max_tokens", 1, "failed")
    fake = Fake(reply(search(URL), text(answer())))
    run(fake)
    assert fake.requests[0]["max_tokens"] == 32000


def test_several_pauses_are_continued():
    fake = Fake(*[reply(search(URL), stop="pause_turn")] * 6, reply(text(answer()), s=0))
    r = run(fake)
    assert len(fake.requests) == 7 and r.usage.rounds == 7 and r.usage.stop_reason == "end_turn"


def test_logging_works_without_migration_007():
    from postgrest.exceptions import APIError

    class Old(SB):
        def rpc(self, name, args=None):
            if name == "finish_ai_check" and "p_stop" in args:
                def fail():
                    raise APIError({"code": "PGRST202", "message": "function not found"})
                return NS(execute=fail)
            return super().rpc(name, args)
    sb = Old({"id": "t"})
    service.run_check(sb, Fake(reply(search(URL), text(answer()))), META, [MIL])
    finish = [a for n, a in sb.calls if n == "finish_ai_check"]
    assert len(finish) == 1 and "p_stop" not in finish[0] and finish[0]["p_status"] == "done"


def test_partial_answer_keeps_covered_criteria():
    child = {**CHILD}
    r = run(Fake(reply(search(URL), text(answer(finding())))), criteria=[MIL, child])
    assert list(r.scores) == ["c1"] and [c["id"] for c in r.missing] == ["c2"]
