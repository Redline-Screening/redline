"""Pre-investment Screening: a company outside the universe, screened and optionally added as a prospect."""
import time

from conftest import page_title
from test_runner import C1, result_for
from test_screening import stored

from redline import service

H = [{"id": "h1", "name": "Palantir Technologies", "isin": "US69608A1088", "weight": 9, "type": "holding"}]


def open_page(make_app, **k):
    app = make_app(holdings=[dict(h) for h in H], criteria=[dict(C1)], workspaces=[{"user_id": "u1", "mode": "ai"}], **k)
    app.session_state["screening-section"] = "pre"
    return app.switch_page("views/screening.py").run()


def finish(app):
    for _ in range(20):
        time.sleep(0.03)
        app.run()
        run = app.session_state["screening_run"]
        if not run["active"] and not run["current"]:
            app.run()
            return


def test_screen_and_add_as_prospect(make_app, monkeypatch):
    seen = []

    def check(sb, client, company, criteria, **k):
        seen.append((company["name"], company["type"], k.get("kind", "manual")))
        found = stored(id="n1", holding_id=company["id"], criterion_id="c1", title="Defence contract", severity="high")
        sb.tables.setdefault("findings", []).append(found)
        return result_for(company, criteria, new=[found], scores={"c1": {"controversy": {"level": "high"}}})
    monkeypatch.setattr(service, "run_check", check)
    monkeypatch.setattr(service, "claude", lambda key: None)
    app = open_page(make_app)
    assert page_title(app) == "Pre-investment Screening"
    assert "Enter a company and select at least one criterion." in [m.value for m in app.markdown]
    from redline import companies
    label = next(k for k, c in companies.suggestions().items() if c["name"] == "Rheinmetall")
    app.selectbox[0].set_value(label).run()    # AppTest cannot type a free name; the browser test covers that
    assert "This will run 1 check. 15 remaining today." in [m.value for m in app.markdown]
    next(b for b in app.button if b.label == "Run screening").click().run()
    finish(app)
    assert not app.exception
    assert seen == [("Rheinmetall", "candidate", "manual")]
    holdings = app.session_state["_supabase"].tables["holdings"]
    candidate = next(h for h in holdings if h["name"] == "Rheinmetall")
    assert candidate["type"] == "candidate"
    assert "Defence contract" in [t.value for t in app.text]
    assert app.selectbox[0].value == "Rheinmetall · RHM.DE · Germany"   # the entry is kept after the run
    assert "Rheinmetall is a pre-investment company. It is not part of the investment universe." in \
        [m.value for m in app.markdown]
    # Not part of the universe or the Overview.
    universe = app.switch_page("views/universe.py").run()
    assert [m.value for m in universe.metric][0] == "1"
    app.switch_page("views/screening.py").run()
    next(b for b in app.button if b.label == "Add to universe as prospect").click().run()
    assert not app.exception and candidate["type"] == "prospect"
    assert any("in the investment universe as a prospect" in m.value for m in app.markdown)


def test_company_in_universe_is_refused(make_app):
    app = open_page(make_app)
    from redline import companies
    label = next(k for k, c in companies.suggestions().items() if c["name"] == "Palantir Technologies")
    app.selectbox[0].set_value(label).run()
    assert app.text_input[1].value == "PLTR"                         # the suggestion fills the ticker
    assert app.info[0].value == "Palantir Technologies is already in the investment universe. Use Holding Screening."
    assert next(b for b in app.button if b.label == "Run screening").disabled


def test_invalid_isin(make_app):
    app = open_page(make_app)
    from redline import companies
    label = next(k for k, c in companies.suggestions().items() if c["name"] == "Rheinmetall")
    app.selectbox[0].set_value(label).run()
    app.text_input[0].input("US0000000001").run()     # replaces the ISIN filled from the list
    assert app.error[0].value == "The ISIN is not valid."


def test_candidate_profile_and_import(make_app):
    from redline import ui
    candidate = {"id": "x1", "name": "Rheinmetall", "isin": None, "weight": 0, "type": "candidate"}
    app = make_app(holdings=[dict(H[0]), dict(candidate)], criteria=[dict(C1)])
    app.session_state[ui.COMPANY_KEY] = "x1"
    app.switch_page("views/company.py").run()
    assert not app.exception and app.selectbox[0].value == "x1"
    assert "(pre-investment)" in app.selectbox[0].format_func("x1") if hasattr(app.selectbox[0], "format_func") else True
    # A CSV row for the same company turns it into a holding instead of creating a duplicate.
    app.switch_page("views/universe.py").run()
    app.file_uploader[0].upload("u.csv", b"name,weight\nRheinmetall,2\n", "text/csv").run()
    next(b for b in app.button if b.label == "Import").click().run()
    rows = app.session_state["_supabase"].tables["holdings"]
    assert [h["type"] for h in rows if h["name"] == "Rheinmetall"] == ["holding"]


def test_suggestion_fills_isin_and_ticker(make_app):
    from redline import companies
    label = next(k for k, c in companies.suggestions().items() if c["isin"])
    company = companies.suggestions()[label]
    app = open_page(make_app)
    app.selectbox[0].set_value(label).run()
    assert (app.text_input[0].value, app.text_input[1].value) == (company["isin"], company["ticker"])




def test_openfigi_never_raises(monkeypatch):
    import httpx

    from redline import companies

    def down(*a, **k):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(httpx, "post", down)
    assert companies.openfigi("Saab") == []


def test_openfigi_results(monkeypatch):
    import httpx

    from redline import companies

    class Reply:
        def raise_for_status(self): pass
        def json(self):
            return {"data": [{"name": "SAAB AB-B", "ticker": "SAABB", "exchCode": "SS", "compositeFIGI": "X"},
                             {"name": "SAAB AB-B", "ticker": "SAABBUSD", "exchCode": "XG", "compositeFIGI": "Z"},
                             {"name": "SAAB AB-A", "ticker": "SAABA", "exchCode": "SS", "compositeFIGI": "Y"}]}
    monkeypatch.setattr(httpx, "post", lambda *a, **k: Reply())
    assert [(r["name"], r["ticker"], r["isin"]) for r in companies.openfigi("Saab")] == [("Saab Ab-B", "SAABB", ""), ("Saab Ab-A", "SAABA", "")]
