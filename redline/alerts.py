"""Alerts: results of Portfolio Monitoring and provider incidents, one card per company. No Streamlit import."""
from redline import rules, summary
from redline.providers import safe_url

OPEN = ("new", "escalated")


def monitoring_view(holdings, criteria, scores, findings, alerts) -> dict:
    """{"breach": [card], "watch": [card], "has_results": bool}. A card holds one company and its lines."""
    active = [c for c in criteria if c["active"]]
    by_ticker = {h.get("ticker") or h["name"]: h for h in holdings}
    cards = {"breach": {}, "watch": {}}
    has_results = False
    for h in holdings:
        for c in active:
            score = scores.get((h["id"], c["id"]))
            if not score or not score.get("monitor_checked"):
                continue
            has_results = True
            state = rules.evaluate(score, c)["state"]
            if state not in cards:
                continue
            pair = [f for f in findings if f["holding_id"] == h["id"] and f["criterion_id"] == c["id"]]
            card = cards[state].setdefault(h["id"], {"company": h, "lines": [], "provider": [], "new": False})
            current = summary.is_current(score, pair, c)
            card["lines"].append({
                "criterion": c, "state": state, "summary": score.get("summary") if current else None,
                "findings": sum(f["status"] == "open" for f in pair), "new": bool(score.get("monitor_new")),
                "checked": score["monitor_checked"],
            })
            card["new"] = card["new"] or bool(score.get("monitor_new"))
    for a in alerts:
        if a.get("origin") != "reprisk" or a.get("status") not in OPEN:
            continue
        for t in a.get("tickers") or []:
            h = by_ticker.get(t)
            if not h:
                continue
            has_results = True
            box = "breach" if h["id"] in cards["breach"] else "watch"
            card = cards[box].setdefault(h["id"], {"company": h, "lines": [], "provider": [], "new": False})
            card["provider"].append({"title": a["title"], "date": a.get("date"), "severity": a["severity"], "url": safe_url(a.get("url"))})
    order = lambda card: (not card["new"], -(card["company"].get("weight") or 0), card["company"]["name"])  # noqa: E731
    return {"breach": sorted(cards["breach"].values(), key=order), "watch": sorted(cards["watch"].values(), key=order),
            "has_results": has_results}


def select(cards, companies=(), criteria=()) -> list[dict]:
    out = []
    for card in cards:
        if companies and card["company"]["id"] not in companies:
            continue
        lines = [x for x in card["lines"] if not criteria or x["criterion"]["id"] in criteria]
        if criteria and not lines:
            continue
        out.append({**card, "lines": lines})
    return out
