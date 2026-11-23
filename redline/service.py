"""Runs one check: limit, AI call, saving. Used by the website. No Streamlit import."""
import uuid

import anthropic

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
    fields = ("id", "holding_id", "criterion_id", "category", "title", "summary", "date", "severity", "sources",
              "status", "first_seen", "last_seen")
    for f in result.new:
        f["id"] = str(uuid.uuid4())
        f["holding_id"] = company["id"]
    records = [{k: f[k] for k in fields} for f in [*result.new, *result.updated]]
    if records:
        sb.table("findings").upsert(records, on_conflict="id").execute()
    if result.alerts:
        sb.table("alerts").upsert([alert_record(f, company) for f in result.alerts], on_conflict="finding_id").execute()
    for cid, columns in result.scores.items():
        if columns:
            sb.table("scores").upsert([{"holding_id": company["id"], "criterion_id": cid, **columns}],
                                      on_conflict="holding_id,criterion_id").execute()


def run_check(sb, client, company, criteria, *, web=True, model=MODEL_MANUAL, max_searches=SEARCHES_MANUAL):
    """Screens one company against the criteria and saves the result.

    Raises LimitReached before anything is spent, or screening.ScreeningError.
    """
    ids = [c["id"] for c in criteria]
    scores = {s["criterion_id"]: s for s in
              sb.table("scores").select("*").eq("holding_id", company["id"]).in_("criterion_id", ids).execute().data}
    findings = sb.table("findings").select("*").eq("holding_id", company["id"]).in_("criterion_id", ids).execute().data

    ticket = sb.rpc("reserve_ai_check", {"p_model": model}).execute().data
    if "id" not in ticket:
        raise LimitReached(BUDGET_MESSAGE if ticket.get("reason") == "budget" else LIMIT_MESSAGE)

    def finish(status, usage):
        sb.rpc("finish_ai_check", {
            "p_id": ticket["id"], "p_status": status, "p_searches": usage.searches, "p_input": usage.input_tokens,
            "p_output": usage.output_tokens, "p_cost": usage.cost(model),
        }).execute()

    try:
        result = screening.screen(client, model=model, company=company, criteria=criteria, scores=scores,
                                  findings=findings, web=web, max_searches=max_searches)
    except screening.ScreeningError as e:
        finish("failed", e.usage)
        raise
    finish("done", result.usage)
    save_result(sb, company, result)
    return result
