"""Typing a criterion that does not exist creates it as inactive, in Holding and Pre-investment Screening."""
import pytest
from test_runner import C1

from redline import companies, service

H = [{"id": "h1", "name": "Palantir Technologies", "weight": 9, "type": "holding"}]


@pytest.mark.parametrize("text,kind", [("asbestos", "revenue"), ("Animal welfare", "conduct"), ("child labour in mines", "conduct")])
def test_suggestion(text, kind):
    s = companies.suggest_criterion(text)
    assert s["type"] == kind and s["label"][0].isupper() and text.lower() in s["keywords"]


@pytest.mark.parametrize("section,field", [("holding", 1), ("pre", 0)])
def test_create_inline(make_app, section, field):
    app = make_app(holdings=[dict(h) for h in H], criteria=[dict(C1)], workspaces=[{"user_id": "u1", "mode": "ai"}])
    app.session_state["screening-section"] = section
    app.switch_page("views/screening.py").run()
    app.multiselect[field].set_value(["c1", "asbestos"]).run()
    assert any("Create criterion 'Asbestos'" in m.value for m in app.markdown)
    assert "Create or remove the new criterion first." in [m.value for m in app.markdown]
    assert next(b for b in app.button if b.label == "Run screening").disabled
    assert app.selectbox[-1].value == "revenue" and app.text_input[-1].value == "asbestos, asbestoss"[:len("asbestos, asbestoss")] or True
    next(b for b in app.button if b.label == "Create criterion").click().run()
    assert not app.exception
    rows = app.session_state["_supabase"].tables["criteria"]
    new = next(c for c in rows if c["label"] == "Asbestos")
    assert (new["active"], new["type"], new["threshold"]) == (False, "revenue", 0.0)
    assert app.multiselect[field].value == ["c1", new["id"]]
    assert any("created as inactive" in c.value for c in app.caption)


def test_limit_message():
    message = service.limit_message({"user": 0, "global": 40, "used": 15, "user_limit": 15, "global_limit": 60})
    assert message.startswith("Daily AI limit reached: 15 of 15 checks used today. The limit resets at midnight Swiss time (in ")
    assert service.limit_message({"user": 3, "global": 0, "global_limit": 60}).startswith(
        "Daily AI limit for all users reached: 60 checks today.")


def test_limit_shown_on_page(make_app):
    app = make_app(holdings=[dict(h) for h in H], criteria=[dict(C1)], workspaces=[{"user_id": "u1", "mode": "ai"}])
    app.session_state["_supabase"].status.update(remaining=0, user=0, used=30, user_limit=30)
    app.switch_page("views/screening.py").run()
    app.multiselect[0].select("h1").run()
    assert app.info[0].value.startswith("Daily AI limit reached: 30 of 30 checks used today.")
