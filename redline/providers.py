"""Provider files: revenue figures and incidents. No Streamlit import."""
import re
from datetime import date, datetime

from redline.importers import ImportProblem, find_company, map_columns, parse_number, valid_isin

_COMPANY = {
    "isin": ["isin", "isin code", "issuer isin"],
    "ticker": ["ticker", "symbol", "issuer ticker"],
    "name": ["company", "company name", "issuer", "issuer name", "name"],
}
FIGURE_COLUMNS = {
    **_COMPANY,
    "category": ["category", "activity", "involvement", "involvement category", "segment", "theme"],
    "revenue": ["revenue %", "revenue", "revenue share", "revenue share %", "revenue percent", "revenue pct",
                "max revenue %", "max revenue", "percent", "pct", "share"],
    "flag": ["flag", "involved", "involvement flag", "indicator"],
}
INCIDENT_COLUMNS = {
    **_COMPANY,
    "date": ["incident date", "date", "publication date"],
    "title": ["headline", "title"],
    "summary": ["summary", "description"],
    "severity": ["severity", "incident severity"],
    "url": ["source url", "url", "link"],
    "topics": ["esg issues", "issues", "issue", "topics", "topic tags", "tags"],
}


def _columns(rows, aliases) -> dict:
    mapping = map_columns(rows[0].keys(), aliases)
    if not {"isin", "ticker", "name"} & mapping.keys():
        raise ImportProblem("No company column found. Use isin, ticker, company or issuer.")
    return mapping


def _match(raw, mapping, companies):
    get = lambda f: raw.get(mapping.get(f, ""), "").strip()  # noqa: E731
    isin = get("isin").upper().replace(" ", "")
    label = get("name") or get("ticker") or get("isin")
    return label, find_company(companies, isin=isin if valid_isin(isin) else "", ticker=get("ticker").upper(), name=get("name"))


def has_keyword(text, keywords) -> bool:
    """Whole words only, with an optional plural: 'coal' does not match 'coalition'."""
    text = str(text).lower()
    return any(re.search(rf"\b{re.escape(k.lower())}(?:e?s)?\b", text) for k in keywords or [] if k)


def guess_criterion(category, criteria):
    for c in criteria:
        if has_keyword(category, [*(c.get("keywords") or []), c["label"]]):
            return c["id"]
    return None


def parse_share(value) -> tuple[float | None, str]:
    """Revenue share and a note. Ranges use their upper bound."""
    text = str(value or "").strip()
    if not text:
        return None, "No revenue share"
    m = re.fullmatch(r"([\d.,]+)\s*%?\s*(?:-|–|to)\s*([\d.,]+)\s*%?", text)
    if m:
        low, number = parse_number(m[1]), parse_number(m[2])
        if low is None or number is None or low > number:
            return None, "Revenue share not readable"
        note = f"upper bound of {text}"
    elif re.fullmatch(r"(?:<|<=|≤)\s*[\d.,]+\s*%?", text):
        number, note = parse_number(re.sub(r"[<=≤]", "", text)), f"upper bound of {text}"
    else:
        number, note = parse_number(text), ""
    if number is None or not 0 <= number <= 100:
        return None, "Revenue share not readable"
    return number, note


def categories(rows) -> list[str]:
    column = _columns(rows, FIGURE_COLUMNS).get("category")
    return sorted({(r.get(column, "") if column else "") or "Uncategorised" for r in rows})


def plan_figures(rows, companies, criteria, category_map, scores, provider, today=None) -> dict:
    """Preview rows and score records. Several rows for one company and criterion: the highest share counts."""
    mapping = _columns(rows, FIGURE_COLUMNS)
    if "revenue" not in mapping:
        raise ImportProblem("No revenue column found. Use a column named revenue, revenue % or percent.")
    labels = {c["id"]: c["label"] for c in criteria}
    today = today or date.today().isoformat()
    preview, best = [], {}
    for i, raw in enumerate(rows, start=2):
        name, company = _match(raw, mapping, companies)
        category = raw.get(mapping.get("category", ""), "").strip() or "Uncategorised"
        criterion = category_map.get(category)
        share, note = parse_share(raw.get(mapping["revenue"]))
        line = {"row": i, "company": company["name"] if company else name, "category": category,
                "criterion": labels.get(criterion, ""), "share": share, "action": "Skip", "note": note}
        preview.append(line)
        if company is None:
            line["note"] = "Company not in the universe"
        elif criterion not in labels:
            line["note"] = "Category not assigned"
        elif share is None:
            flag = raw.get(mapping.get("flag", ""), "").strip().lower()
            if note == "No revenue share" and re.match(r"(y|true|1)", flag):
                line["note"] = "Involvement flagged without a revenue share; analyst assessment required"
        else:
            key = (company["id"], criterion)
            if key in best and best[key]["line"]["share"] >= share:
                line["note"] = f"Higher share in row {best[key]['line']['row']}"
                continue
            if key in best:
                best[key]["line"].update(action="Skip", note=f"Higher share in row {i}")
            line["action"] = "Import"
            old = scores.get(key) or {}
            if old.get("exposure") is not None:
                line["note"] = "; ".join(x for x in (note, f"Replaces {old.get('source') or 'existing figure'}") if x)
            best[key] = {"line": line, "record": {
                "holding_id": company["id"], "criterion_id": criterion, "exposure": share,
                "exposure_kind": "provider", "source": provider, "exposure_date": today,
                "basis": f"{category}" + (f", {note}" if note else ""),
                "confidence": "high", "rationale": None, "signals": [],
            }}
    return {"rows": preview, "records": [b["record"] for b in best.values()]}


def parse_date(value) -> str | None:
    """ISO date, or None when missing or ambiguous (such as 03/04/2026)."""
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d.%m.%Y", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    if re.match(r"\d{4}-\d{2}-\d{2}[T ]", text):
        return parse_date(text[:10])
    found = set()
    for fmt in ("%d/%m/%Y", "%m/%d/%Y"):
        try:
            found.add(datetime.strptime(text, fmt).date().isoformat())
        except ValueError:
            continue
    return found.pop() if len(found) == 1 else None


def safe_url(value) -> str | None:
    url = str(value or "").strip()
    return url if re.match(r"https?://[^\s]+$", url, re.I) else None


def _severity(text) -> str | None:
    t = str(text or "").strip().lower()
    if re.search(r"high|severe|3", t):
        return "high"
    if re.search(r"med|2", t):
        return "medium"
    if re.search(r"low|1", t):
        return "low"
    return None


def _identity(alert):
    return alert.get("url") or (str(alert.get("title")).lower(), alert.get("date"), tuple(alert.get("tickers") or []))


def plan_incidents(rows, companies, criteria, existing, source="RepRisk") -> dict:
    mapping = _columns(rows, INCIDENT_COLUMNS)
    if "title" not in mapping:
        raise ImportProblem("No headline column found. Use a column named headline or title.")
    seen = {_identity(a) for a in existing}
    preview, records = [], []
    for i, raw in enumerate(rows, start=2):
        get = lambda f: raw.get(mapping.get(f, ""), "").strip()  # noqa: E731
        name, company = _match(raw, mapping, companies)
        line = {"row": i, "company": company["name"] if company else name, "title": get("title"), "action": "Skip", "note": ""}
        preview.append(line)
        if company is None:
            line["note"] = "Company not in the universe"
            continue
        if not get("title"):
            line["note"] = "No headline"
            continue
        text = " ".join(get(f) for f in ("topics", "title", "summary"))
        matched = [c for c in criteria if has_keyword(text, c.get("keywords"))]
        severity, when, url = _severity(get("severity")), parse_date(get("date")), safe_url(get("url"))
        record = {
            "title": get("title")[:140], "summary": get("summary") or None, "date": when,
            "severity": severity or "medium", "tickers": [company.get("ticker") or company["name"]],
            "criteria": [c["id"] for c in matched], "url": url, "origin": "reprisk", "source": source, "status": "new",
        }
        if _identity(record) in seen:
            line["note"] = "Already recorded"
            continue
        seen.add(_identity(record))
        records.append(record)
        notes = [", ".join(c["label"] for c in matched) or "No matching criterion"]
        if get("date") and when is None:
            notes.append("date not clear")
        if severity is None:
            notes.append("severity not given, set to medium")
        line.update(action="Import", note="; ".join(notes))
    return {"rows": preview, "records": records}
