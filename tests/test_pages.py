"""Every page renders without an error for a signed-in user."""
import pytest

PAGES = {
    "overview": "Overview",
    "universe": "Investment Universe",
    "criteria": "Exclusion Criteria",
    "sources": "Data Sources",
    "screening": "Screening",
    "risk": "Risk Assessment",
    "alerts": "Alerts",
}


@pytest.mark.parametrize("name,title", PAGES.items())
def test_page(make_app, name, title):
    app = make_app()
    if name != "overview":
        app.switch_page(f"views/{name}.py").run()
    assert not app.exception
    assert app.title[0].value == title
