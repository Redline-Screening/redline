# Redline

Exclusion screening for fund universes. School project built with Streamlit, Supabase and the Anthropic API.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # fill in the values
.venv/bin/streamlit run streamlit_app.py
```

Tests: `.venv/bin/python -m pytest`

## Database (Supabase)

1. Create a project, open **SQL Editor**, paste `supabase/schema.sql` and run it.
2. Under **Authentication → Sign In / Providers → Email**, switch off **Confirm email**.
3. With two test accounts, run `.venv/bin/python tests/check_rls.py`. It confirms that neither account can reach the other's data.

## Deployment (Streamlit Community Cloud)

1. Sign in at share.streamlit.io with GitHub and grant access to the repository's organization.
2. **Create app**: repository `Redline-Screening/redline`, branch `main`, main file `streamlit_app.py`.
3. **Advanced settings**: select Python 3.14 (3.12 and 3.13 also have all required packages) and paste the contents of `.streamlit/secrets.toml` into **Secrets**.
4. Deploy, then make the app public under **Share** so that classmates can reach the sign-in page.

Every push to `main` updates the app. Secrets never belong in git, and the Supabase secret key is not used by the app.
