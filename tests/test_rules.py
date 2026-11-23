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
    assert r.evaluate({"controversy": con("medium")}, {**C, "controversy_limit": "medium"})["state"] == "breach"
    assert r.evaluate({"controversy": con("high")}, {**C, "controversy_limit": "severe"})["state"] == "watch"
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
