"""Live check that two accounts cannot reach each other's data.

Run by hand: .venv/bin/python tests/check_rls.py
Asks for two test accounts (nothing is stored) and removes the rows it creates.
"""
import getpass
import tomllib
from pathlib import Path

from postgrest.exceptions import APIError
from supabase import create_client

secrets = tomllib.loads((Path(__file__).resolve().parent.parent / ".streamlit/secrets.toml").read_text())


def login(label):
    email = input(f"{label} email: ").strip()
    sb = create_client(secrets["SUPABASE_URL"], secrets["SUPABASE_PUBLISHABLE_KEY"])
    sb.auth.sign_in_with_password({"email": email, "password": getpass.getpass(f"{label} password: ")})
    return sb


failures = 0


def check(text, ok):
    global failures
    failures += not ok
    print(("PASS  " if ok else "FAIL  ") + text)


def refused(call):
    try:
        call()
    except APIError as e:
        return e.code in ("42501", "23503", "P0001")  # RLS/permission, foreign key, trigger
    return False


a, b = login("Account A"), login("Account B")
uid_a = a.auth.get_user().user.id
uid_b = b.auth.get_user().user.id
if uid_a == uid_b:
    raise SystemExit("Use two different accounts.")
anon = create_client(secrets["SUPABASE_URL"], secrets["SUPABASE_PUBLISHABLE_KEY"])

hold = a.table("holdings").insert({"name": "RLS check"}).execute().data[0]["id"]
crit = a.table("criteria").insert({"label": "RLS check"}).execute().data[0]["id"]
b_crit = b.table("criteria").insert({"label": "RLS check B"}).execute().data[0]["id"]
alert = a.table("alerts").insert({"title": "RLS check"}).execute().data[0]["id"]
try:
    a.table("scores").insert({"holding_id": hold, "criterion_id": crit, "exposure": 12, "exposure_kind": "provider"}).execute()
    a.table("workspaces").upsert({"user_id": uid_a}).execute()

    for table, col, val in [("holdings", "id", hold), ("criteria", "id", crit), ("alerts", "id", alert),
                            ("scores", "holding_id", hold), ("workspaces", "user_id", uid_a)]:
        check(f"A reads own {table}", len(a.table(table).select("*").eq(col, val).execute().data) == 1)
        check(f"B cannot read A's {table}", b.table(table).select("*").eq(col, val).execute().data == [])
        check(f"B cannot change A's {table}", b.table(table).update({"user_id": uid_b}).eq(col, val).execute().data == [])
        check(f"B cannot delete A's {table}", b.table(table).delete().eq(col, val).execute().data == [])
        check(f"Signed out cannot read {table}", refused(lambda: anon.table(table).select("*").execute()))

    check("B cannot insert a row for A", refused(lambda: b.table("holdings").insert({"name": "x", "user_id": uid_a}).execute()))
    check("B cannot score A's company", refused(lambda: b.table("scores").insert({"holding_id": hold, "criterion_id": b_crit}).execute()))
    check("AI cannot replace a provider figure", refused(lambda: a.table("scores").update(
        {"exposure": 1, "exposure_kind": "ai_web"}).eq("holding_id", hold).execute()))
    f = a.table("findings").insert({"holding_id": hold, "criterion_id": crit, "title": "RLS check", "summary": "x",
                                    "severity": "low", "sources": [{"url": "https://example.com", "title": "x"}]}).execute().data[0]["id"]
    check("B cannot read A's findings", b.table("findings").select("*").eq("id", f).execute().data == [])
    check("B cannot delete A's findings", b.table("findings").delete().eq("id", f).execute().data == [])
    check("B cannot link an alert to A's finding", refused(lambda: b.table("alerts").insert({"title": "x", "finding_id": f}).execute()))
    check("B cannot record AI checks", refused(lambda: b.table("ai_checks").insert({"user_id": uid_b, "kind": "manual", "model": "x"}).execute()))
    check("B cannot raise the daily limit", refused(lambda: b.table("accounts").insert({"user_id": uid_b, "daily_limit": 999}).execute()))
    check("Signed out cannot reserve AI checks", refused(lambda: anon.rpc("reserve_ai_check", {"p_model": "x"}).execute()))
    check("B cannot change the budget", refused(lambda: b.table("ai_budget").update({"total": 999}).eq("kind", "manual").execute()))
finally:
    a.table("holdings").delete().eq("id", hold).execute()
    a.table("criteria").delete().eq("id", crit).execute()
    a.table("alerts").delete().eq("id", alert).execute()
    b.table("criteria").delete().eq("id", b_crit).execute()

print("All checks passed." if not failures else f"{failures} check(s) failed.")
raise SystemExit(bool(failures))
