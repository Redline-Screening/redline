from conftest import notice, page_title
from pathlib import Path

import pytest

from redline import importers as im
from redline import providers as pv
from redline.criteria import from_templates

ROOT = Path(__file__).resolve().parent.parent / "sample"


def table(name):
    return im.read_table((ROOT / name).read_text())


UNIVERSE = im.plan_universe_import(table("universe.csv"), [])["records"]
MIL = from_templates(["military"], [])[0]


def figures(rows, scores=None, companies=UNIVERSE, crit=(MIL,)):
    names = pv.categories(rows)
    return pv.plan_figures(rows, companies, list(crit), {n: pv.guess_criterion(n, crit) for n in names}, scores or {}, "MSCI", "2026-11-24")


def test_sample_figures():
    plan = figures(table("provider.csv"))
    assert [r["action"] for r in plan["rows"]] == ["Import"] * 3 + ["Skip"] * 3
    assert [r["exposure"] for r in plan["records"]] == [25, 0, 5]
    assert plan["records"][2]["basis"].endswith("upper bound of 0-5%")
    notes = [r["note"] for r in plan["rows"]]
    assert "analyst assessment required" in notes[3]
    assert notes[4] == "Company not in the universe" and notes[5] == "Category not assigned"
    assert {r["exposure_kind"] for r in plan["records"]} == {"provider"}


def test_highest_share_counts_and_replacement_is_shown():
    rows = im.read_table("issuer,category,revenue\nApple,military,2\nApple,military,9\nApple,military,4\n")
    apple = next(c for c in UNIVERSE if c["name"] == "Apple")
    plan = figures(rows, {(apple["id"], MIL["id"]): {"exposure": 1, "source": "Analyst"}})
    assert [r["exposure"] for r in plan["records"]] == [9]
    assert [r["action"] for r in plan["rows"]] == ["Skip", "Import", "Skip"]
    assert "Replaces Analyst" in plan["rows"][1]["note"]


@pytest.mark.parametrize("text,value", [
    ("5", 5), ("2,5%", 2.5), ("5-10", 10), ("5 – 10 %", 10), ("<5%", 5), (">50", None), ("101", None),
    ("-3", None), ("10-5", None), ("", None), ("n/a", None),
])
def test_shares(text, value):
    assert pv.parse_share(text)[0] == value


def test_keywords_are_whole_words():
    assert pv.has_keyword("Weapons deal", ["weapon"])
    assert not pv.has_keyword("A coalition in Las Vegas", ["coal", "gas"])


@pytest.mark.parametrize("text,value", [
    ("2026-11-20", "2026-11-20"), ("20.11.2026", "2026-11-20"), ("20/11/2026", "2026-11-20"), ("11/20/2026", "2026-11-20"),
    ("03/04/2026", None), ("20 Nov 2026", "2026-11-20"), ("2026-11-20T10:00:00", "2026-11-20"), ("", None), ("soon", None),
])
def test_dates(text, value):
    assert pv.parse_date(text) == value


def test_incidents():
    plan = pv.plan_incidents(table("incidents.csv"), UNIVERSE, [MIL], [])
    assert [r["action"] for r in plan["rows"]] == ["Import", "Skip"]
    a = plan["records"][0]
    assert (a["severity"], a["date"], a["tickers"], a["criteria"]) == ("high", "2026-11-20", ["LOGN"], [MIL["id"]])
    again = pv.plan_incidents(table("incidents.csv"), UNIVERSE, [MIL], [a])
    assert again["records"] == [] and again["rows"][0]["note"] == "Already recorded"


def test_unsafe_links_are_dropped():
    assert pv.safe_url("javascript:alert(1)") is None
    assert pv.safe_url("https://example.com/a") == "https://example.com/a"


@pytest.mark.parametrize("text", ["category,revenue\na,1\n", "isin,category\nUS0378331005,a\n"])
def test_unusable_files(text):
    with pytest.raises(im.ImportProblem):
        figures(im.read_table(text))


def click(app, label):
    next(b for b in app.button if b.label == label).click().run()
    assert not app.exception


def test_page(make_app):
    app = make_app(holdings=[dict(h) for h in UNIVERSE], criteria=[dict(MIL)]).switch_page("views/sources.py").run()
    assert not app.file_uploader
    app.radio[0].set_value("both").run()
    click(app, "Save method")
    tables = app.session_state["_supabase"].tables
    assert tables["workspaces"][0]["mode"] == "both"
    app.file_uploader[0].upload("provider.csv", (ROOT / "provider.csv").read_bytes(), "text/csv").run()
    assert next(b for b in app.button if b.label == "Import figures").disabled
    app.selectbox[0].select("other").run()
    click(app, "Import figures")
    assert notice(app) == "Provider figures imported: 3."
    app.file_uploader[1].upload("incidents.csv", (ROOT / "incidents.csv").read_bytes(), "text/csv").run()
    click(app, "Import incidents")
    assert len(tables["alerts"]) == 1
    assert tables["workspaces"][0]["mode"] == "both"
    assert set(tables["workspaces"][0]["providers"]) == {"other", "reprisk"}
    app.switch_page("views/overview.py").run()
    assert [m.value for m in app.metric] == ["8.00%", "0.00%", "0", "3 of 10"]
    app.switch_page("views/alerts.py").run()
    assert not app.exception
    assert "Logitech International" in [m.value for m in app.markdown if m.value.startswith("**")][0]
    assert "Sample incident for import testing" in [t.value for t in app.text]
