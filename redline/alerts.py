"""Alerts joined with their findings. No Streamlit import."""
from redline.providers import safe_url

SEVERITIES = ("severe", "high", "medium", "low")
OPEN = ("new", "escalated")


def join(alerts, findings, holdings, criteria) -> list[dict]:
    """One entry per alert: company, criteria, date and all sources. Newest first, unknown dates last."""
    by_finding = {f["id"]: f for f in findings}
    by_id = {h["id"]: h for h in holdings}
    labels = {c["id"]: c["label"] for c in criteria}
    names = {}
    for h in holdings:
        names.setdefault(h.get("ticker") or h["name"], h["name"])
    out = []
    for a in alerts:
        f = by_finding.get(a.get("finding_id"))
        ids = {h.get("ticker") or h["name"]: h["id"] for h in holdings}
        if f and f["holding_id"] in by_id:
            companies, holding_ids = [by_id[f["holding_id"]]["name"]], [f["holding_id"]]
        else:
            companies = [names.get(t, t) for t in a.get("tickers") or []]
            holding_ids = [ids[t] for t in a.get("tickers") or [] if t in ids]
        url = safe_url(a.get("url"))
        out.append({
            "id": a["id"], "title": a["title"], "summary": a.get("summary"), "severity": a["severity"], "status": a["status"],
            "companies": companies, "holding_ids": holding_ids, "criteria": [labels[i] for i in a.get("criteria") or [] if i in labels],
            "criterion_ids": a.get("criteria") or [], "date": a.get("date"),
            "date_type": (f.get("date_type") or "reported") if f else None, "category": f["category"] if f else None, "finding": f,
            "date_precision": f.get("date_precision") if f else None,
            "sources": f["sources"] if f else [{"url": url}] if url else [], "origin": a.get("source"),
        })
    return sorted(out, key=lambda a: a["date"] or "", reverse=True)


def select(entries, *, open_only=True, severities=(), companies=(), criteria=()) -> list[dict]:
    return [
        e for e in entries
        if (not open_only or e["status"] in OPEN)
        and (not severities or e["severity"] in severities)
        and (not companies or set(companies) & set(e["companies"]))
        and (not criteria or set(criteria) & set(e["criterion_ids"]))
    ]
