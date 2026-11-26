"""Queue of checks. Each check runs in its own thread and never touches Streamlit.

A check is removed from the queue before it starts, so it cannot run (and be billed)
twice. The page starts the next one; without an open page nothing further starts.
"""
import threading
from datetime import date, timedelta

from redline import screening, service
from redline.constants import MODEL_MONITOR, MONITOR_FIRST_DAYS, SEARCHES_MONITOR
from redline.rules import evaluate, revenue_source, uses_revenue


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


def monitoring_jobs(companies, criteria, scores, today=None) -> list[dict]:
    """One check per monitored company, covering all active criteria, for incidents since its last monitoring check."""
    today = today or date.today()
    first = (today - timedelta(days=MONITOR_FIRST_DAYS)).isoformat()
    jobs = []
    for h in sorted(companies, key=lambda c: (-(c.get("weight") or 0), c["name"])):
        checked = [(scores.get((h["id"], c["id"])) or {}).get("monitor_checked") for c in criteria]
        since = min(checked) if all(checked) else first
        jobs.append({"company": h, "criteria": list(criteria), "since": since})
    return jobs


def new_run(jobs, *, web, estimate, kind="manual") -> dict:
    return {"jobs": list(jobs), "total": len(jobs), "done": 0, "findings": 0, "alerts": 0, "left_out": 0, "checks": [], "failed_jobs": [], "errors": [], "failures": 0,
            "current": None, "active": True, "message": None, "web": web, "estimate": estimate, "kind": kind,
            "lock": threading.Lock()}


def label(job) -> str:
    names = ", ".join(c["label"] for c in job["criteria"])
    return f"{job['company']['name']} – {names}"


def check_records(job, result=None, error=None) -> list[dict]:
    """What one check changed, per criterion: status before and after, and its findings."""
    out = []
    for c in job["criteria"]:
        entry = {"company_id": job["company"].get("id"), "company": job["company"]["name"], "criterion_id": c["id"],
                 "criterion": c["label"], "error": error, "new": [], "updated": [], "unchanged": 0, "before": None, "after": None,
                 "exposure": None, "revenue_source": None}
        if result is not None:
            old = (result.before or {}).get(c["id"])
            entry["before"] = evaluate(old, c)["state"]
            after = {**(old or {}), **result.scores.get(c["id"], {})}
            entry["after"] = evaluate(after, c)["state"]
            if uses_revenue(c) and after.get("exposure") is not None:     # current figure, also if this check kept it
                entry["exposure"], entry["revenue_source"] = after["exposure"], revenue_source(after)
            entry["new"] = [f["id"] for f in result.new if f["criterion_id"] == c["id"]]
            entry["updated"] = [f["id"] for f in result.updated if f["criterion_id"] == c["id"]]
            seen = set(entry["updated"])
            entry["unchanged"] = sum(f["criterion_id"] == c["id"] and f["id"] not in seen for f in result.known)
        out.append(entry)
    return out


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
        options = {}
        if run.get("kind") == "monitor":
            options = {"kind": "monitor", "model": MODEL_MONITOR, "max_searches": SEARCHES_MONITOR, "since": job.get("since")}
        result = service.run_check(sb, client, job["company"], job["criteria"], web=run["web"], estimate=run["estimate"], **options)
        covered = [c for c in job["criteria"] if c["id"] in result.scores]
        service.refresh_summaries(sb, client, job["company"], covered)
        missing = getattr(result, "missing", None) or []
        if missing and not job.get("retry"):
            # The answer left out some criteria: check those again in a separate check.
            with run["lock"]:
                run["jobs"].insert(0, {**job, "criteria": missing, "retry": True})
                run["total"] += 1
        elif missing:
            message = "The AI answer did not cover this criterion. Nothing was saved."
            run["errors"].append(f"{label({**job, 'criteria': missing})}: {message}")
            run["checks"] += check_records({**job, "criteria": missing}, error=message)
            run["failed_jobs"].append({**job, "criteria": missing, "retry": False})
        run["done"] += 1
        run["failures"] = 0
        run["findings"] += len(result.new)
        run["alerts"] += len(result.alerts)
        run["left_out"] += result.left_out
        run["checks"] += check_records({**job, "criteria": covered}, result)
    except service.LimitReached as e:
        run["jobs"].insert(0, job)
        run["message"], run["active"] = str(e), False
    except screening.ScreeningError as e:
        run["errors"].append(f"{label(job)}: {e}")
        run["checks"] += check_records(job, error=str(e))
        run["failed_jobs"].append({**job, "retry": False})
        run["failures"] += 1
        if run["failures"] >= 2:    # avoid paying for a series of failures
            run["message"], run["active"] = "The screening was stopped after two failed checks in a row.", False
    except Exception:
        run["errors"].append(f"{label(job)}: the result could not be saved.")
        run["checks"] += check_records(job, error="The result could not be saved.")
        run["message"], run["active"] = "The screening was stopped because the database did not respond.", False
    finally:
        run["current"] = None
