"""Live check that the demo account cannot change anything.

Run by hand: .venv/bin/python tests/check_demo.py
If a check fails, run supabase/demo_copy.sql again to restore the demo data.
"""
import tomllib
from pathlib import Path

from postgrest.exceptions import APIError
from supabase import create_client

secrets = tomllib.loads((Path(__file__).resolve().parent.parent / ".streamlit/secrets.toml").read_text())
sb = create_client(secrets["SUPABASE_URL"], secrets["SUPABASE_PUBLISHABLE_KEY"])
uid = sb.auth.sign_in_with_password({"email": secrets["DEMO_EMAIL"], "password": secrets["DEMO_PASSWORD"]}).user.id
account = sb.table("accounts").select("*").execute().data
if not account or not account[0]["read_only"]:
    raise SystemExit("This account is not marked read-only. Nothing was tested.")

failures = 0


def check(text, ok):
    global failures
    failures += not ok
    print(("PASS  " if ok else "FAIL  ") + text)


def refused(call):
    try:
        return call().data == []
    except APIError as e:
        return e.code == "42501"


holding = sb.table("holdings").select("*").limit(1).execute().data[0]
for table, row in {"holdings": {"name": "Demo check"}, "criteria": {"label": "Demo check"}, "alerts": {"title": "Demo check"},
                   "workspaces": {"user_id": uid}}.items():
    check(f"cannot add to {table}", refused(lambda: sb.table(table).insert(row).execute()))
for table, values in {"holdings": {"weight": 1}, "criteria": {"watch_at": 1}, "scores": {"likelihood": 1}, "findings": {"severity": "low"},
                      "alerts": {"status": "dismissed"}, "workspaces": {"name": "x"}}.items():
    check(f"cannot change {table}", refused(lambda: sb.table(table).update(values).eq("user_id", uid).execute()))
check("cannot overwrite a company", refused(lambda: sb.table("holdings").upsert({**holding, "name": "x"}).execute()))
for table in ("alerts", "findings", "scores", "holdings", "criteria", "workspaces"):
    count = len(sb.table(table).select("*").execute().data)
    refused(lambda: sb.table(table).delete().eq("user_id", uid).execute())
    check(f"cannot delete from {table} ({count} rows)", len(sb.table(table).select("*").execute().data) == count > 0)
check("cannot change own account settings", refused(lambda: sb.table("accounts").update({"read_only": False}).eq("user_id", uid).execute()))
check("cannot reserve AI checks", "id" not in sb.rpc("reserve_ai_check", {"p_model": "x"}).execute().data)
print("All checks passed." if not failures else f"{failures} check(s) failed.")
raise SystemExit(bool(failures))
