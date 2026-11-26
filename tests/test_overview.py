def H(i, name, w):
    return {"id": i, "name": name, "weight": w, "type": "holding"}


CRIT = {"id": "c1", "key": "military", "label": "Military", "threshold": 0, "watch_at": 50,
        "controversy_limit": "high", "active": True, "sort": 1, "keywords": []}


def test_new_account_shows_setup(make_app):
    app = make_app()
    assert not app.exception
    assert [b.label for b in app.button if b.key and b.key.startswith("setup-")] == ["Continue"] * 3
    assert not app.metric


def test_assessment_reaches_overview(make_app):
    app = make_app(holdings=[H("1", "Meta", 6), H("2", "SAP", 5)], criteria=[CRIT])
    assert [m.value for m in app.metric] == ["0.00%", "0.00%", "0", "0 of 2"]
    app.switch_page("views/company.py").run()
    assert not app.exception
    app.number_input[0].set_value(5.0)
    next(b for b in app.button if b.label == "Save assessment").click().run()
    assert app.success[0].value == "Assessment saved."
    app.selectbox[0].select("2").run()
    app.number_input[0].set_value(0.0)
    app.number_input[1].set_value(60.0)
    next(b for b in app.button if b.label == "Save assessment").click().run()
    assert not app.exception
    app.switch_page("views/overview.py").run()
    assert not app.exception
    assert [m.value for m in app.metric] == ["6.00%", "5.00%", "0", "2 of 2"]
    table = app.dataframe[0].value
    assert list(table["Status"]) == ["Breach", "Watch"]
    assert list(table["Source"]) == ["Analyst", "Analyst"]


def test_exposure_is_required(make_app):
    app = make_app(holdings=[H("1", "Meta", 6)], criteria=[CRIT]).switch_page("views/company.py").run()
    next(b for b in app.button if b.label == "Save assessment").click().run()
    assert app.error[0].value == "Enter a revenue exposure."


def test_assessment_keeps_controversy(make_app):
    score = {"holding_id": "1", "criterion_id": "c1", "exposure": None, "controversy": {"level": "high"}}
    app = make_app(holdings=[H("1", "Meta", 6)], criteria=[CRIT], scores=[score]).switch_page("views/company.py").run()
    app.number_input[0].set_value(0.0)
    next(b for b in app.button if b.label == "Save assessment").click().run()
    saved = app.session_state["_supabase"].tables["scores"][0]
    assert saved["controversy"] == {"level": "high"} and saved["exposure"] == 0


def test_delete_needs_confirmation(make_app):
    rows = [{"holding_id": "1", "criterion_id": "c1", "exposure": 5, "exposure_kind": "analyst"},
            {"holding_id": "2", "criterion_id": "c1", "exposure": 5, "exposure_kind": "analyst"}]
    app = make_app(holdings=[H("1", "Meta", 6), H("2", "SAP", 5)], criteria=[CRIT], scores=rows).switch_page("views/company.py").run()
    next(b for b in app.button if b.label == "Delete assessment").click().run()
    # AppTest cannot run buttons inside dialogs, so this checks only that confirmation is required.
    assert not app.exception
    assert any(b.label == "Delete" for b in app.button)
    assert len(rows) == 2


def test_only_the_chosen_score_is_deleted(make_app, monkeypatch):
    from redline import auth, db
    rows = [{"holding_id": "1", "criterion_id": "c1"}, {"holding_id": "1", "criterion_id": "c2"},
            {"holding_id": "2", "criterion_id": "c1"}]
    client = make_app(scores=rows).session_state["_supabase"]
    monkeypatch.setattr(auth, "client", lambda: client)
    db.delete_score("1", "c1")
    assert rows == [{"holding_id": "1", "criterion_id": "c2"}, {"holding_id": "2", "criterion_id": "c1"}]


def test_conduct_criterion(make_app):
    conduct = {**CRIT, "type": "conduct", "threshold": None}
    score = {"holding_id": "1", "criterion_id": "c1", "controversy": {"level": "high"}}
    app = make_app(holdings=[H("1", "Meta", 6)], criteria=[conduct], scores=[score])
    assert not app.exception and app.metric[0].value == "6.00%"
    app.switch_page("views/company.py").run()
    assert not app.exception
    assert [n.label for n in app.number_input] == ["Likelihood of increase (0\u2013100)"]
    app.number_input[0].set_value(40.0)
    next(b for b in app.button if b.label == "Save assessment").click().run()
    saved = app.session_state["_supabase"].tables["scores"][0]
    assert saved["likelihood"] == 40 and "exposure" not in saved and saved["controversy"] == {"level": "high"}
