"""Breach, watch and clear rules. No Streamlit import."""

from redline.constants import fixed_limit

LEVELS = ("none", "low", "medium", "high", "severe")
LABELS = {"breach": "Breach", "watch": "Watch", "clear": "Clear", "partial": "Partly screened", "na": "Not screened"}


def _rank(level) -> int:
    return LEVELS.index(level) if level in LEVELS else 0


def controversy_level(score):
    return ((score or {}).get("controversy") or {}).get("level")


def breach_level(criterion) -> str:
    """Incident severity that counts as a breach."""
    return fixed_limit(criterion.get("type") or "both", criterion.get("key")) or criterion.get("controversy_limit") or "high"


def uses_revenue(criterion) -> bool:
    return criterion.get("type") != "conduct"


def is_unsourced(score) -> bool:
    """AI revenue estimate without a source for the figure. It can cause Watch, never Breach."""
    return str((score or {}).get("exposure_kind") or "").startswith("ai") and not score.get("exposure_sourced")


def revenue_source(score) -> str | None:
    score = score or {}
    if score.get("exposure") is None:
        return None
    if str(score.get("exposure_kind") or "").startswith("ai"):
        return "Unsourced estimate" if is_unsourced(score) else "AI estimate, sourced"
    return score.get("source")


def evaluate(score, criterion) -> dict:
    """Status of one company for one criterion: {state, reasons}."""
    score = score or {}
    exposure, likelihood, level = score.get("exposure"), score.get("likelihood"), controversy_level(score)
    if not uses_revenue(criterion):
        exposure = None
    threshold = criterion.get("threshold") or 0
    watch_at = 50 if criterion.get("watch_at") is None else criterion["watch_at"]

    reasons = []
    above = exposure is not None and exposure > threshold
    unsourced = is_unsourced(score)
    if above and not unsourced:
        reasons.append("Revenue")
    if _rank(level) >= _rank(breach_level(criterion)):
        reasons.append("Controversy")
    if reasons:
        return {"state": "breach", "reasons": reasons}
    if _rank(level) >= _rank("medium"):
        reasons.append("Controversy")
    if above and unsourced:
        reasons.append("Unsourced estimate")
    if likelihood is not None and likelihood >= watch_at:
        reasons.append("Likelihood")
    if reasons:
        return {"state": "watch", "reasons": reasons}
    # A likelihood below the watch level alone does not show that a company is clear.
    return {"state": "na" if exposure is None and level is None else "clear", "reasons": []}


def evaluate_holding(holding, criteria, scores) -> dict:
    """Overall status. scores: {(holding id, criterion id): score}.

    A company is clear only when every active criterion has been screened.
    """
    results = [
        {"criterion": c, "score": scores.get((holding["id"], c["id"])),
         **evaluate(scores.get((holding["id"], c["id"])), c)}
        for c in criteria
    ]
    states = {r["state"] for r in results}
    if "breach" in states:
        state = "breach"
    elif "watch" in states:
        state = "watch"
    elif states == {"clear"}:
        state = "clear"
    elif "clear" in states:
        state = "partial"
    else:
        state = "na"
    return {"state": state, "results": results}


def index_scores(rows) -> dict:
    return {(s["holding_id"], s["criterion_id"]): s for s in rows}


def overview(holdings, criteria, scores) -> dict:
    """Figures for the Overview page (holdings only, active criteria only)."""
    held = [h for h in holdings if h["type"] == "holding"]
    active = [c for c in criteria if c["active"]]
    evaluated = [(h, evaluate_holding(h, active, scores)) for h in held]
    weight = lambda h: h["weight"] or 0  # noqa: E731
    summary = {
        s: {"count": sum(e["state"] == s for _, e in evaluated),
            "weight": sum(weight(h) for h, e in evaluated if e["state"] == s)}
        for s in LABELS
    }
    flagged = [
        {"holding": h, **r}
        for h, e in evaluated for r in e["results"] if r["state"] in ("breach", "watch")
    ]
    flagged.sort(key=lambda r: (r["state"] != "breach", -weight(r["holding"])))
    by_criterion = []
    for i, c in enumerate(active):
        column = [(h, e["results"][i]["state"]) for h, e in evaluated]
        by_criterion.append({
            "criterion": c,
            "weight": sum(weight(h) for h, s in column if s == "breach"),
            **{s: sum(x == s for _, x in column) for s in ("breach", "watch", "na")},
        })
    complete = sum(all(r["state"] != "na" for r in e["results"]) and bool(active) for _, e in evaluated)
    return {"held": len(held), "active": len(active), "summary": summary, "flagged": flagged,
            "by_criterion": by_criterion, "complete": complete}
