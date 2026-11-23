from pathlib import Path

import pytest

from redline import importers as im

SAMPLE = Path(__file__).resolve().parent.parent / "sample" / "universe.csv"


def rows(text):
    return im.read_table(text)


def test_sample_and_reimport():
    table = rows(im.decode(SAMPLE.read_bytes()))
    first = im.plan_universe_import(table, [])
    assert [r["action"] for r in first["rows"]] == ["Add"] * 10
    assert all(r["note"] == "" for r in first["rows"])
    assert sum(r["weight"] for r in first["records"]) == 70
    again = im.plan_universe_import(table, first["records"])
    assert [r["action"] for r in again["rows"]] == ["Update"] * 10
    assert {r["id"] for r in again["records"]} == {r["id"] for r in first["records"]}


@pytest.mark.parametrize("text,value", [
    ("2.5", 2.5), ("2,5", 2.5), ("2,5 %", 2.5), ("1.234,5", 1234.5), ("1,234.5", 1234.5),
    ("1'234.5", 1234.5), ("-3,2", -3.2), ("−3.2", -3.2), ("12", 12), ("", None), ("n/a", None), ("nan", None), ("inf", None),
])
def test_numbers(text, value):
    assert im.parse_number(text) == value


def test_semicolon_and_decimal_comma():
    plan = im.plan_universe_import(rows("Name;ISIN;Weight %\nNestlé;CH0038863350;4,5\n"), [])
    assert plan["records"][0]["weight"] == 4.5
    assert plan["records"][0]["name"] == "Nestlé"


def test_quoted_comma_and_cp1252():
    table = rows(im.decode('name,weight\n"Nestlé, S.A.",1\n'.encode("cp1252")))
    assert table[0]["name"] == "Nestlé, S.A."


def test_isin():
    assert im.valid_isin("US0378331005")
    assert not im.valid_isin("US0378331006")
    plan = im.plan_universe_import(rows("name,isin\nApple,US0378331006\n"), [])
    assert plan["records"][0]["isin"] is None and "Invalid ISIN" in plan["rows"][0]["note"]


def test_similar_names_are_not_merged():
    existing = [{"id": "1", "name": "American Express", "type": "holding"}]
    assert im.find_company(existing, name="American Airlines") is None
    assert im.find_company(existing, name="AMERICAN  EXPRESS")["id"] == "1"


def test_different_isins_are_never_the_same_company():
    existing = [{"id": "1", "name": "X", "ticker": "SAP", "isin": "DE0007164600"}]
    assert im.find_company(existing, isin="US0378331005", ticker="SAP", name="X") is None


def test_update_keeps_fields_missing_from_the_file():
    existing = [{"id": "1", "name": "Apple", "isin": "US0378331005", "ticker": "AAPL", "weight": 5, "type": "prospect", "sector": "IT"}]
    rec = im.plan_universe_import(rows("name,isin,weight\nApple Inc,US0378331005,6\n"), existing)["records"][0]
    assert (rec["weight"], rec["type"], rec["sector"], rec["ticker"]) == (6, "prospect", "IT", "AAPL")


def test_duplicates_and_blank_names_are_skipped():
    plan = im.plan_universe_import(rows("name,ticker\nApple,AAPL\nApple,AAPL\n,MSFT\n"), [])
    assert [r["action"] for r in plan["rows"]] == ["Add", "Skip", "Skip"]


@pytest.mark.parametrize("text", ["", "name,weight\n", "foo,bar\n1,2\n"])
def test_unusable_files(text):
    with pytest.raises(im.ImportProblem):
        im.plan_universe_import(rows(text), [])


def test_diff_edits():
    before = [{"id": "1", "name": "A", "weight": 1, "type": "holding"}, {"id": "2", "name": "B", "weight": 2, "type": "holding"}]
    after = [{**before[0], "weight": 1.0, "ytd": float("nan")}, {**before[1], "weight": 3.0}]
    changed, removed = im.diff_edits(before, after)
    assert [c["id"] for c in changed] == ["2"] and not removed
    changed, removed = im.diff_edits(before, [{**before[0], "remove": True}, before[1]])
    assert not changed and removed == ["1"]
    with pytest.raises(im.ImportProblem):
        im.diff_edits(before, [{**before[0], "isin": "BAD"}])
