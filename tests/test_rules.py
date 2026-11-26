import pytest

from redline import rules as r

C = {"id": "c", "label": "Military", "threshold": 0, "watch_at": 50, "controversy_limit": "high", "active": True}


def con(level):
    return {"level": level}


@pytest.mark.parametrize("score,state,reasons", [
    (None, "na", []),
    ({}, "na", []),
    ({"exposure": 5}, "breach", ["Revenue"]),
    ({"exposure": 0}, "clear", []),
    ({"exposure": 0, "likelihood": 60}, "watch", ["Likelihood"]),
    ({"exposure": 0, "likelihood": 50}, "watch", ["Likelihood"]),
    ({"exposure": 0, "likelihood": 49}, "clear", []),
    ({"likelihood": 60}, "watch", ["Likelihood"]),
    ({"likelihood": 10}, "na", []),
    ({"controversy": con("none")}, "clear", []),
    ({"controversy": con("low")}, "clear", []),
    ({"controversy": con("medium")}, "watch", ["Controversy"]),
    ({"controversy": con("high")}, "breach", ["Controversy"]),
    ({"exposure": 1, "controversy": con("severe")}, "breach", ["Revenue", "Controversy"]),
])
def test_rules(score, state, reasons):
    assert r.evaluate(score, C) == {"state": state, "reasons": reasons}


def test_limits_are_respected():
    assert r.evaluate({"exposure": 5}, {**C, "threshold": 5})["state"] == "clear"
    assert r.evaluate({"exposure": 5.1}, {**C, "threshold": 5})["state"] == "breach"
    assert r.evaluate({"exposure": 0, "likelihood": 0}, {**C, "watch_at": 0})["state"] == "watch"


def test_partly_screened_is_not_clear():
    two = [C, {**C, "id": "d"}]
    h = {"id": "h"}
    assert r.evaluate_holding(h, two, {("h", "c"): {"exposure": 0}})["state"] == "partial"
    assert r.evaluate_holding(h, two, {("h", "c"): {"exposure": 0}, ("h", "d"): {"exposure": 0}})["state"] == "clear"
    assert r.evaluate_holding(h, two, {("h", "c"): {"exposure": 9}})["state"] == "breach"
    assert r.evaluate_holding(h, [], {})["state"] == "na"


def test_overview_ignores_prospects_and_inactive_criteria():
    holdings = [{"id": "1", "weight": 10, "type": "holding"}, {"id": "2", "weight": 5, "type": "holding"},
                {"id": "3", "weight": 50, "type": "prospect"}]
    criteria = [C, {**C, "id": "off", "active": False}]
    scores = {("1", "c"): {"exposure": 5}, ("3", "c"): {"exposure": 5}, ("2", "off"): {"exposure": 5}}
    o = r.overview(holdings, criteria, scores)
    assert o["summary"]["breach"] == {"count": 1, "weight": 10}
    assert o["summary"]["na"] == {"count": 1, "weight": 5}
    assert (o["complete"], o["held"], len(o["flagged"])) == (1, 2, 1)
    assert o["by_criterion"][0]["weight"] == 10


@pytest.mark.parametrize("kind,limit,level,state", [
    ("revenue", "severe", "severe", "breach"), ("revenue", "severe", "high", "watch"), ("revenue", "severe", "medium", "watch"),
    ("both", "high", "high", "breach"), ("both", "medium", "medium", "watch"),
    ("conduct", "medium", "medium", "breach"), ("conduct", "high", "medium", "watch"),
    ("conduct", "severe", "high", "watch"), ("conduct", "high", "low", "clear"),
])
def test_incident_levels_by_type(kind, limit, level, state):
    c = {**C, "type": kind, "controversy_limit": limit, "threshold": None if kind == "conduct" else 0}
    assert r.evaluate({"controversy": con(level)}, c)["state"] == state


def test_conduct_ignores_revenue():
    c = {**C, "type": "conduct", "threshold": None}
    assert r.evaluate({"exposure": 90}, c)["state"] == "na"


def test_small_unsourced_estimate_without_findings_is_no_evidence():
    ai = {"exposure_kind": "ai_web"}
    assert r.evaluate({**ai, "exposure": 0.1}, C)["state"] == "clear"
    assert r.evaluate({**ai, "exposure": 0.1, "controversy": con("none")}, C)["state"] == "clear"
    assert r.evaluate({**ai, "exposure": 1.0}, C) == {"state": "watch", "reasons": ["Unsourced estimate"]}
    assert r.evaluate({**ai, "exposure": 0.1, "controversy": con("low")}, C) == {"state": "watch", "reasons": ["Unsourced estimate"]}
    assert r.evaluate({**ai, "exposure": 0.1, "exposure_sourced": True}, C)["state"] == "breach"
    assert r.evaluate({"exposure": 0.1, "exposure_kind": "provider"}, C)["state"] == "breach"
