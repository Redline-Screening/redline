"""Company search: a bundled list of large listed companies, and OpenFIGI as a free fallback. No Streamlit import."""
import csv
from functools import lru_cache
from pathlib import Path

import httpx

from redline.importers import norm_name

LIST = Path(__file__).resolve().parent.parent / "data" / "companies.csv"
OPENFIGI = "https://api.openfigi.com/v3/search"


@lru_cache(maxsize=1)
def bundled() -> tuple[dict, ...]:
    with LIST.open(encoding="utf-8") as f:
        return tuple(csv.DictReader(f))


def label(c) -> str:
    return " · ".join(x for x in (c["name"], c.get("ticker"), c.get("isin"), c.get("country")) if x)


def suggestions() -> dict:
    """Display label -> company, for the search field."""
    return {label(c): c for c in bundled()}


def openfigi(query: str, limit: int = 8) -> list[dict]:
    """Listed equities matching a name. OpenFIGI returns names and tickers, but no ISINs. Never raises."""
    if len(query.strip()) < 2:
        return []
    try:
        reply = httpx.post(OPENFIGI, json={"query": query.strip(), "securityType2": "Common Stock", "marketSecDes": "Equity"},
                           timeout=8)
        reply.raise_for_status()
        data = reply.json().get("data") or []
    except (httpx.HTTPError, ValueError):
        return []
    out, seen = [], set()
    for d in data:
        key = (d.get("name") or "").upper()       # one entry per company, not per exchange
        if key in seen or not key:
            continue
        seen.add(key)
        out.append({"name": d["name"].title(), "ticker": d.get("ticker") or "", "isin": "", "country": "",
                    "exchange": d.get("exchCode") or ""})
        if len(out) >= limit:
            break
    return out


# ---------- new criteria typed in a criteria field ----------

CONDUCT_WORDS = ("labour", "labor", "rights", "abuse", "corruption", "bribery", "fraud", "discrimination", "harassment",
                 "pollution", "deforestation", "spill", "violation", "safety", "privacy", "slavery", "trafficking",
                 "sanction", "tax evasion", "money laundering", "misconduct", "welfare", "displacement", "land grab")


def suggest_criterion(text: str) -> dict:
    """Type and keywords suggested for a criterion typed by the user (no AI)."""
    label = text.strip()[:80]
    label = label[:1].upper() + label[1:]
    lowered = label.lower()
    kind = "conduct" if any(w in lowered for w in CONDUCT_WORDS) else "revenue"
    words = [lowered] + ([lowered + "s"] if not lowered.endswith("s") and " " not in lowered else [])
    return {"label": label, "type": kind, "keywords": ", ".join(dict.fromkeys(words))}


def is_known(name, companies) -> bool:
    return any(norm_name(c["name"]) == norm_name(name) for c in companies)
