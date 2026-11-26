from redline import db

CRIT = {"id": "c1", "key": "m", "label": "Military", "type": "both", "threshold": 0, "watch_at": 50,
        "controversy_limit": "high", "active": True, "sort": 1, "keywords": []}
H = {"id": "h1", "name": "Meta", "weight": 6, "type": "holding"}


def demo(make_app):
    return make_app(holdings=[dict(H)], criteria=[dict(CRIT)], workspaces=[{"user_id": "u1", "mode": "ai"}],
                    accounts=[{"user_id": "u1", "read_only": True}])


def test_address_is_hidden(make_app):
    app = demo(make_app)
    assert not app.exception
    shown = [t.value for t in app.sidebar.text]
    assert "Demo account" in shown and "a@example.com" not in shown
    assert "a@example.com" in [t.value for t in make_app().sidebar.text]


def test_changes_are_refused_with_a_message(make_app):
    app = demo(make_app).switch_page("views/universe.py").run()
    app.text_input[0].input("Roche")
    next(b for b in app.button if b.label == "Add company").click().run()
    assert app.error[0].value == db.READ_ONLY
    assert len(app.session_state["_supabase"].tables["holdings"]) == 1
    app.switch_page("views/company.py").run()
    app.number_input[0].set_value(5.0)
    next(b for b in app.button if b.label == "Save assessment").click().run()
    assert app.error[0].value == db.READ_ONLY


def test_no_screening(make_app):
    app = demo(make_app).switch_page("views/screening.py").run()
    assert not app.exception
    assert app.info[0].value == "AI checks are not available in the demo account."
    assert next(b for b in app.button if b.label == "Run screening").disabled


def test_button_only_with_settings(make_app):
    app = make_app(signed_in=False)
    assert not any(b.label == "View demo" for b in app.button)
    app.secrets["DEMO_EMAIL"], app.secrets["DEMO_PASSWORD"] = "d@example.com", "right-password"
    app.run()
    next(b for b in app.button if b.label == "View demo").click().run()
    assert not app.exception and app.title[0].value == "Overview"


def test_demo_failure_shows_no_details(make_app):
    app = make_app(signed_in=False)
    app.secrets["DEMO_EMAIL"], app.secrets["DEMO_PASSWORD"] = "d@example.com", "wrong"
    app.run()
    next(b for b in app.button if b.label == "View demo").click().run()
    assert app.error[0].value == "The demo account is currently unavailable."
