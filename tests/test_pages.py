"""Every page renders without an error for a signed-in user."""
from conftest import notice, page_title
import pytest

PAGES = {
    "overview": "Overview",
    "universe": "Investment Universe",
    "criteria": "Exclusion Criteria",
    "sources": "Data Sources",
    "screening": "Holding Screening",
    "company": "Company Profile",
    "alerts": "Alerts",
    "help": "Help",
}


@pytest.mark.parametrize("name,title", PAGES.items())
def test_page(make_app, name, title):
    app = make_app()
    if name != "overview":
        app.switch_page(f"views/{name}.py").run()
    assert not app.exception
    assert page_title(app) == title


def test_screening_opens_on_portfolio_monitoring(make_app):
    from conftest import page_title
    app = make_app()
    del app.session_state["screening-section"]
    app.switch_page("views/screening.py").run()
    assert page_title(app) == "Portfolio Monitoring"
