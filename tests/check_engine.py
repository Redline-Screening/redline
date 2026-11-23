"""One real, billed check. Run by hand: .venv/bin/python tests/check_engine.py"""
import getpass
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from supabase import create_client  # noqa: E402

from redline import rules, screening, service  # noqa: E402
from redline.constants import MODEL_MANUAL, SEARCHES_MANUAL  # noqa: E402

secrets = tomllib.loads((ROOT / ".streamlit/secrets.toml").read_text())
sb = create_client(secrets["SUPABASE_URL"], secrets["SUPABASE_PUBLISHABLE_KEY"])
sb.auth.sign_in_with_password({"email": input("Email: ").strip(), "password": getpass.getpass("Password: ")})


def pick(table, label, column, default):
    rows = sb.table(table).select("*").execute().data
    text = input(f"{label} [{default}]: ").strip() or default
    hits = [r for r in rows if text.lower() in r[column].lower()]
    if len(hits) != 1:
        raise SystemExit(f"{len(hits)} matches for {text}.")
    return hits[0]


company = pick("holdings", "Company", "name", "Meta")
criterion = pick("criteria", "Criterion", "label", "Military")
print("Remaining today:", sb.rpc("ai_status").execute().data)
print(f"This will run 1 check: {company['name']} / {criterion['label']}, {MODEL_MANUAL}, up to {SEARCHES_MANUAL} searches.")
if input("Run this billed check? Type yes: ").strip().lower() != "yes":
    raise SystemExit("Nothing was run.")
try:
    result = service.run_check(sb, service.claude(secrets["ANTHROPIC_API_KEY"]), company, [criterion])
except (service.LimitReached, screening.ScreeningError) as e:
    raise SystemExit(str(e))

saved = sb.table("scores").select("*").eq("holding_id", company["id"]).eq("criterion_id", criterion["id"]).execute().data[0]
print("\nStatus:", rules.LABELS[rules.evaluate(saved, criterion)["state"]], "| revenue %:", saved["exposure"], saved["source"],
      "| likelihood:", saved["likelihood"], "| level:", saved["controversy"]["level"])
for f in sb.table("findings").select("*").eq("holding_id", company["id"]).eq("criterion_id", criterion["id"]).execute().data:
    print(f"\n[{f['severity']}] {f['title']} ({f['date'] or 'Date unknown'}, {f['category']})\n  {f['summary']}")
    for s in f["sources"]:
        print("  ", s["url"])
u = result.usage
print(f"\nNew findings: {len(result.new)}, seen again: {len(result.updated)}, alerts: {len(result.alerts)}")
print(f"Searches: {u.searches}, input tokens: {u.input_tokens}, output tokens: {u.output_tokens}, cost: ${u.cost(MODEL_MANUAL):.3f}")
