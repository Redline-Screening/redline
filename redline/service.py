"""Runs one check: limit, AI call, saving. Used by the website. No Streamlit import."""
import uuid

import anthropic
from postgrest.exceptions import APIError

from redline import screening
from redline.constants import MODEL_MANUAL, SEARCHES_MANUAL

LIMIT_MESSAGE = "Daily AI limit reached, try again tomorrow."
BUDGET_MESSAGE = "The AI budget of this project has been used. Saved results remain available."


class LimitReached(Exception):
    """Message suitable for display."""


def claude(api_key):
    # One retry only: a repeated request may be billed again.
    return anthropic.Anthropic(api_key=api_key, timeout=300, max_retries=1)


def alert_record(finding, company) -> dict:
    return {
        "finding_id": finding["id"], "title": finding["title"], "summary": finding["summary"], "date": finding["date"],
        "severity": finding["severity"], "tickers": [company.get("ticker") or company["name"]],
        "criteria": [finding["criterion_id"]], "url": finding["sources"][0]["url"],
        "origin": "web", "source": "AI web search", "status": "new",
    }


def save_result(sb, company, result) -> None:
    fields = ("id", "holding_id", "criterion_id", "category", "title", "summary", "date", "date_type", "date_precision", "severity", "involvement", "evidence",
              "legal_status", "sources",
              "status", "first_seen", "last_seen")
    for f in result.new:
        f["id"] = str(uuid.uuid4())
        f["holding_id"] = company["id"]
    for f in result.updated:
        f.setdefault("date_type", "reported")
        f.setdefault("date_precision", "day")
    records = [{k: f.get(k) for k in fields} for f in [*result.new, *result.updated]]
    if records:
        sb.table("findings").upsert(records, on_conflict="id").execute()
    if result.alerts:
        sb.table("alerts").upsert([alert_record(f, company) for f in result.alerts], on_conflict="finding_id").execute()
    raised = {f["id"] for f in result.alerts}
    for f in result.updated:    # corrected text reaches an existing alert without reopening it
        if f["id"] not in raised:
            sb.table("alerts").update({"title": f["title"], "summary": f["summary"], "date": f["date"], "severity": f["severity"]}) \
                .eq("finding_id", f["id"]).execute()
            if screening.LEVELS.index(f["severity"]) < screening.LEVELS.index("medium"):
                sb.table("alerts").update({"status": "reviewed"}).eq("finding_id", f["id"]) \
                    .in_("status", ["new", "escalated"]).execute()
    for cid, columns in result.scores.items():
        if columns:
            sb.table("scores").upsert([{"holding_id": company["id"], "criterion_id": cid, **columns}],
                                      on_conflict="holding_id,criterion_id").execute()


def run_check(sb, client, company, criteria, *, web=True, estimate=True, model=MODEL_MANUAL, max_searches=SEARCHES_MANUAL,
              kind="manual", since=None):
    """Screens one company against the criteria and saves the result.

    Raises LimitReached before anything is spent, or screening.ScreeningError.
    """
    ids = [c["id"] for c in criteria]
    scores = {s["criterion_id"]: s for s in
              sb.table("scores").select("*").eq("holding_id", company["id"]).in_("criterion_id", ids).execute().data}
    findings = sb.table("findings").select("*").eq("holding_id", company["id"]).in_("criterion_id", ids).execute().data

    ticket = sb.rpc("reserve_monitor_check" if kind == "monitor" else "reserve_ai_check", {"p_model": model}).execute().data
    if "id" not in ticket:
        raise LimitReached(BUDGET_MESSAGE if ticket.get("reason") == "budget" else LIMIT_MESSAGE)

    def finish(status, usage):
        args = {"p_id": ticket["id"], "p_status": status, "p_searches": usage.searches, "p_input": usage.input_tokens,
                "p_output": usage.output_tokens, "p_cost": usage.cost(model)}
        try:
            sb.rpc("finish_ai_check", {**args, "p_stop": usage.stop_reason, "p_rounds": usage.rounds}).execute()
        except APIError:    # database without migration 007
            sb.rpc("finish_ai_check", args).execute()

    try:
        result = screening.screen(client, model=model, company=company, criteria=criteria, scores=scores,
                                  findings=findings, web=web, max_searches=max_searches, estimate=estimate,
                                  since=since)
    except screening.ScreeningError as e:
        finish("failed", e.usage)
        raise
    finish("done", result.usage)
    save_result(sb, company, result)
    result.before, result.known = scores, findings
    if kind == "monitor":
        mark_monitored(sb, company, [c for c in criteria if c["id"] in result.scores], result)
    return result


def log_monitoring(sb, company, criteria) -> None:
    """Writes today's alert log entries for one monitored company, after its summaries are up to date.

    Earlier days are never changed; a repeated check on the same day replaces that day's entries.
    """
    from redline import alertlog
    day = alertlog.today()
    ids = [c["id"] for c in criteria]
    scores = {s["criterion_id"]: s for s in
              sb.table("scores").select("*").eq("holding_id", company["id"]).in_("criterion_id", ids).execute().data}
    findings = sb.table("findings").select("*").eq("holding_id", company["id"]).in_("criterion_id", ids).execute().data
    earlier = sb.table("alert_log").select("*").eq("holding_id", company["id"]).eq("origin", "monitoring") \
        .lt("day", day.isoformat()).execute().data
    previous = {}
    for r in sorted(earlier, key=lambda r: r["day"]):
        previous[r["criterion_id"]] = r["status"]
    rows = alertlog.monitoring_rows(company, criteria, scores, findings, previous, day)
    sb.table("alert_log").delete().eq("holding_id", company["id"]).eq("origin", "monitoring") \
        .eq("day", day.isoformat()).in_("criterion_id", ids).execute()
    if rows:
        sb.table("alert_log").insert(rows).execute()


def mark_monitored(sb, company, criteria, result) -> None:
    """Records the monitoring check and whether it found something new for Alerts."""
    from datetime import date

    from redline.rules import evaluate
    for c in criteria:
        before = evaluate(result.before.get(c["id"]), c)["state"]
        after = evaluate({**(result.before.get(c["id"]) or {}), **result.scores.get(c["id"], {})}, c)["state"]
        found = any(f["criterion_id"] == c["id"] for f in result.new)
        new = after in ("breach", "watch") and (after != before or found)
        sb.table("scores").update({"monitor_checked": date.today().isoformat(), "monitor_new": new}) \
            .eq("holding_id", company["id"]).eq("criterion_id", c["id"]).execute()


def refresh_summaries(sb, client, company, criteria) -> None:
    """Brings the status summaries up to date. Problems never affect the saved result."""
    from redline import summary
    for c in criteria:
        try:
            summary.refresh(sb, client, company, c)
        except Exception:
            continue


def dismiss(sb, finding) -> None:
    """Dismisses a finding and its alert, and recalculates the incident level."""
    pair = {"holding_id": finding["holding_id"], "criterion_id": finding["criterion_id"]}
    sb.table("findings").update({"status": "dismissed"}).eq("id", finding["id"]).execute()
    sb.table("alerts").update({"status": "dismissed"}).eq("finding_id", finding["id"]).execute()
    rest = sb.table("findings").select("*").eq("holding_id", pair["holding_id"]).eq("criterion_id", pair["criterion_id"]).execute().data
    scores = sb.table("scores").select("*").eq("holding_id", pair["holding_id"]).eq("criterion_id", pair["criterion_id"]).execute().data
    if scores:
        checked = (scores[0].get("controversy") or {}).get("checked")
        sb.table("scores").update({"controversy": screening.controversy(rest, checked)}) \
            .eq("holding_id", pair["holding_id"]).eq("criterion_id", pair["criterion_id"]).execute()
