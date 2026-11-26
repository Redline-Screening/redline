"""Landing page and sign-in. AppTest cannot operate dialogs, so the sign-in logic is tested directly."""
import pytest

from redline import auth


def test_signed_out_sees_the_landing_page(make_app):
    app = make_app(signed_in=False)
    assert not app.exception
    body = " ".join(h.proto.body for h in app.get("html"))
    assert "Know when your portfolio crosses the line." in body
    assert "alerts you when a holding crosses a line" in body
    assert [b.label for b in app.button][:2] == ["Sign in", "Create account"]
    assert "funded privately" not in " ".join(c.value for c in app.caption)
    assert not app.sidebar.button


def test_analysis_card_opens_the_sections(make_app):
    app = make_app(signed_in=False)
    assert not app.expander
    next(b for b in app.button if b.label == "›").click().run()
    assert [e.label for e in app.expander] == ["Portfolio Monitoring", "Holding Screening", "Pre-investment Screening",
                                               "Company Profiles", "Alerts"]


@pytest.fixture
def client(make_app, monkeypatch):
    c = make_app(signed_in=False).session_state["_supabase"]
    monkeypatch.setattr(auth, "client", lambda: c)
    monkeypatch.setattr(auth.st, "secrets", {"SIGNUP_ACCESS_CODE": "the-code"})
    return c


def test_wrong_password(client):
    with pytest.raises(auth.SignInError, match="Email or password is incorrect."):
        auth.sign_in("a@example.com", "wrong")


def test_sign_in(client):
    auth.sign_in("a@example.com", "right-password")
    assert client.auth.session is not None


def test_wrong_access_code_creates_no_account(client):
    with pytest.raises(auth.SignInError, match="The access code is not valid."):
        auth.sign_up("b@example.com", "right-password", "nope")
    assert client.auth.sign_ups == 0


def test_right_access_code(client):
    assert auth.sign_up("b@example.com", "right-password", "the-code") is True


def test_sign_out(make_app):
    app = make_app()
    auth_ = app.session_state["_supabase"].auth
    next(b for b in app.sidebar.button if b.label == "Sign out").click().run()
    assert auth_.session is None


def test_missing_settings(make_app):
    app = make_app(secrets=False)
    assert "Configuration incomplete" in app.error[0].value
