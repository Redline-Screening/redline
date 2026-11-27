"""Daily Portfolio Monitoring, run by GitHub Actions at 07:00 Swiss time.

Same checks, limits and budget as "Run now": Haiku, 2 web searches, one check per monitored company
covering all active criteria, incidents since the last monitoring check, at most 10 checks per day
across all users and $4 in total. Results go to Alerts through the alert log.

Environment: SUPABASE_URL, SUPABASE_SECRET_KEY, ANTHROPIC_API_KEY.
Options: --force runs before 07:00 (manual runs); --again repeats today's automatic run.
The log contains counts only, never company names or e-mail addresses (Actions logs can be public).
"""
import argparse
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from redline import alertlog, runner, screening, service
from redline.constants import MODEL_MONITOR, SEARCHES_MONITOR

ZURICH = ZoneInfo("Europe/Zurich")
START_HOUR = 7


def due(workspace, today, again) -> bool:
    if not (workspace.get("monitor") or {}).get("enabled"):
        return False
    done_today = workspace.get("monitor_last_run") == today.isoformat() and workspace.get("monitor_last_kind") == "automatic"
    return again or not done_today


def run_user(sb, client, uid, today) -> dict:
    """Monitors one user's selected companies. Stops at the daily or total limit and reports it in "stopped"."""
    holdings = [h for h in sb.table("holdings").select("*").eq("user_id", uid).execute().data
                if h.get("monitored") and h["type"] == "holding"]
    criteria = [c for c in sb.table("criteria").select("*").eq("user_id", uid).execute().data if c["active"]]
    counts = {"companies": len(holdings), "done": 0, "failed": 0, "stopped": None}
    if not holdings or not criteria:
        return counts
    scores = {(s["holding_id"], s["criterion_id"]): s for s in sb.table("scores").select("*").eq("user_id", uid).execute().data}
    options = {"kind": "monitor", "model": MODEL_MONITOR, "max_searches": SEARCHES_MONITOR, "uid": uid}
    for job in runner.monitoring_jobs(holdings, criteria, scores, today=today):
        todo = job["criteria"]
        for attempt in range(2):        # a criterion left out of the answer is checked once more on its own
            try:
                result = service.run_check(sb, client, job["company"], todo, since=job["since"], **options)
            except service.LimitReached as e:
                counts["stopped"] = str(e)
                return counts
            except screening.ScreeningError:
                counts["failed"] += 1
                break
            covered = [c for c in todo if c["id"] in result.scores]
            service.refresh_summaries(sb, client, job["company"], covered, uid)
            if covered:
                service.log_monitoring(sb, job["company"], covered, uid)
            counts["done"] += 1
            todo = getattr(result, "missing", None) or []
            if not todo:
                break
            if attempt == 1:
                counts["failed"] += 1
    return counts


def main(argv=None) -> int:
    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("--force", action="store_true", help="run even before 07:00 Swiss time")
    args.add_argument("--again", action="store_true", help="repeat although today's automatic run is done")
    options = args.parse_args(argv)

    now = datetime.now(ZURICH)
    if now.hour < START_HOUR and not options.force:
        print(f"Not yet {START_HOUR:02d}:00 Swiss time; nothing to do.")
        return 0
    missing = [k for k in ("SUPABASE_URL", "SUPABASE_SECRET_KEY", "ANTHROPIC_API_KEY") if not os.environ.get(k)]
    if missing:
        print("Missing settings: " + ", ".join(missing))
        return 1

    from supabase import create_client
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    client = service.claude(os.environ["ANTHROPIC_API_KEY"])
    today = alertlog.today()
    read_only = {a["user_id"] for a in sb.table("accounts").select("*").execute().data if a.get("read_only")}
    workspaces = [w for w in sb.table("workspaces").select("*").execute().data
                  if w["user_id"] not in read_only and due(w, today, options.again)]
    print(f"{today}: {len(workspaces)} workspace(s) with daily monitoring due.")
    total = {"done": 0, "failed": 0}
    for n, w in enumerate(workspaces, start=1):
        counts = run_user(sb, client, w["user_id"], today)
        stopped = counts["stopped"]
        note = f"Automatic run: {counts['done']} checks, {counts['failed']} failed."
        if stopped:
            note += f" Stopped: {stopped}"
        sb.table("workspaces").update({"monitor_last_run": today.isoformat(), "monitor_last_kind": "automatic",
                                       "monitor_note": note}).eq("user_id", w["user_id"]).execute()
        print(f"Workspace {n}: {counts['companies']} companies, {counts['done']} checks, {counts['failed']} failed"
              + (" (limit reached, run stopped)" if stopped else "") + ".")
        total["done"] += counts["done"]
        total["failed"] += counts["failed"]
        if stopped:
            print("Daily or total monitoring limit reached; remaining workspaces are skipped.")
            break
    print(f"Done: {total['done']} checks, {total['failed']} failed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
