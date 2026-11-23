from pathlib import Path

SAMPLE = Path(__file__).resolve().parent.parent / "sample" / "universe.csv"


def open_page(make_app):
    return make_app().switch_page("views/universe.py").run()


def data(app):
    return app.session_state["_supabase"].tables["holdings"]


def upload(app):
    app.file_uploader[0].upload("universe.csv", SAMPLE.read_bytes(), "text/csv").run()
    next(b for b in app.button if b.label == "Import").click().run()
    assert not app.exception


def test_import_twice_creates_no_duplicates(make_app):
    app = open_page(make_app)
    upload(app)
    assert len(data(app)) == 10
    assert [m.value for m in app.metric] == ["10", "70.00%", "0"]
    assert app.success[0].value == "Companies added: 10. Updated: 0."
    upload(app)
    assert len(data(app)) == 10
    assert app.success[0].value == "Companies added: 0. Updated: 10."


def add(app, name, isin=""):
    app.text_input[0].input(name)
    app.text_input[2].input(isin)
    next(b for b in app.button if b.label == "Add company").click().run()
    assert not app.exception
    return app


def test_add_company(make_app):
    app = add(open_page(make_app), "Roche", "CH0012032048")
    assert data(app)[0]["name"] == "Roche"
    add(app, "ROCHE")
    assert app.error[0].value == "This company is already in the universe."
    add(app, "Other", "XX")
    assert app.error[0].value == "The ISIN is not valid."
    assert len(data(app)) == 1
