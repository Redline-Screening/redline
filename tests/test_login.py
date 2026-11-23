def fill(app, offset, *values):
    for i, v in enumerate(values):
        app.text_input[offset + i].input(v)
    return app


def test_signed_out_sees_only_login(make_app):
    app = make_app(signed_in=False)
    assert not app.exception
    assert app.title[0].value == "Redline"


def test_wrong_password(make_app):
    app = fill(make_app(signed_in=False), 0, "a@example.com", "wrong")
    app.button[0].click().run()
    assert app.error[0].value == "Email or password is incorrect."


def test_sign_in_and_out(make_app):
    app = fill(make_app(signed_in=False), 0, "a@example.com", "right-password")
    app.button[0].click().run()
    assert app.title[0].value == "Overview"
    auth = app.session_state["_supabase"].auth
    app.button(key="sign-out").click().run()
    assert auth.session is None


def test_wrong_access_code_creates_no_account(make_app):
    app = fill(make_app(signed_in=False), 2, "b@example.com", "right-password", "nope")
    app.button[1].click().run()
    assert app.error[0].value == "The access code is not valid."
    assert app.session_state["_supabase"].auth.sign_ups == 0


def test_right_access_code(make_app):
    app = fill(make_app(signed_in=False), 2, "b@example.com", "right-password", "the-code")
    app.button[1].click().run()
    assert app.title[0].value == "Overview"


def test_missing_settings(make_app):
    app = make_app(secrets=False)
    assert "Configuration incomplete" in app.error[0].value
