"""Queue of checks. Each check runs in its own thread and never touches Streamlit.

A check is removed from the queue before it starts, so it cannot run (and be billed)
twice. The page starts the next one; without an open page nothing further starts.
"""
import threading
from datetime import date, timedelta

from redline import screening, service
from redline.rules import uses_revenue


def build_jobs(companies, criteria, scores, *, web, skip_days=0, today=None) -> list[dict]:
    """Web: one check per company and criterion. Quick estimate: one per company. Largest weight first."""
    today = today or date.today()
    limit = (today - timedelta(days=skip_days)).isoformat()
    ordered = sorted(companies, key=lambda c: (-(c.get("weight") or 0), c["name"]))
    if not web:
        usable = [c for c in criteria if uses_revenue(c)]
        return [{"company": h, "criteria": usable} for h in ordered] if usable else []

    def recent(h, c):
        checked = ((scores.get((h["id"], c["id"])) or {}).get("controversy") or {}).get("checked")
        return bool(skip_days and checked and checked > limit)

    return [{"company": h, "criteria": [c]} for h in ordered for c in criteria if not recent(h, c)]


def new_run(jobs, *, web, estimate) -> dict:
    return {"jobs": list(jobs), "total": len(jobs), "done": 0, "findings": 0, "alerts": 0, "errors": [], "failures": 0,
            "current": None, "active": True, "message": None, "web": web, "estimate": estimate, "lock": threading.Lock()}


def label(job) -> str:
    names = ", ".join(c["label"] for c in job["criteria"])
    return f"{job['company']['name']} – {names}"


def start_next(run, sb, client) -> threading.Thread | None:
    """Starts one check if the run is active and none is in progress."""
    with run["lock"]:
        if not run["active"] or run["current"]:
            return None
        if not run["jobs"]:
            run["active"] = False
            return None
        job = run["jobs"].pop(0)
        run["current"] = label(job)
    thread = threading.Thread(target=_work, args=(run, job, sb, client), daemon=True)
    thread.start()
    return thread


def _work(run, job, sb, client) -> None:
    try:
        result = service.run_check(sb, client, job["company"], job["criteria"], web=run["web"], estimate=run["estimate"])
        run["done"] += 1
        run["failures"] = 0
        run["findings"] += len(result.new)
        run["alerts"] += len(result.alerts)
    except service.LimitReached as e:
        run["jobs"].insert(0, job)
        run["message"], run["active"] = str(e), False
    except screening.ScreeningError as e:
        run["errors"].append(f"{label(job)}: {e}")
        run["failures"] += 1
        if run["failures"] >= 2:    # avoid paying for a series of failures
            run["message"], run["active"] = "The screening was stopped after two failed checks in a row.", False
    except Exception:
        run["errors"].append(f"{label(job)}: the result could not be saved.")
        run["message"], run["active"] = "The screening was stopped because the database did not respond.", False
    finally:
        run["current"] = None
