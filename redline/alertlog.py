"""Dated alert log and its Excel export. No Streamlit import, no AI calls."""
import io
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from redline import rules

ZURICH = ZoneInfo("Europe/Zurich")
ORIGINS = {"monitoring": "Portfolio Monitoring", "provider": "Provider import"}
STATUS = {"breach": "Breach", "watch": "Watch", "provider": "Provider incident"}
MAX_SOURCES = 3


def today() -> date:
    """Monitoring days follow Swiss time."""
    return datetime.now(ZURICH).date()


def _severity(findings) -> str | None:
    open_ = [f["severity"] for f in findings if f["status"] == "open"]
    return max(open_, key=rules.LEVELS.index) if open_ else None


def _sources(findings) -> list[dict]:
    out, seen = [], set()
    ordered = sorted((f for f in findings if f["status"] == "open"), key=lambda f: -rules.LEVELS.index(f["severity"]))
    for f in ordered:
        for s in f["sources"]:
            if s["url"] not in seen:
                seen.add(s["url"])
                out.append({"url": s["url"], "title": s.get("title") or s["url"]})
    return out[:MAX_SOURCES]


def change(previous, status) -> str:
    """Compared with the latest earlier entry of the same company and criterion."""
    if previous is None:
        return "New"
    if previous == status:
        return "Unchanged"
    return f"{STATUS.get(previous, previous)} → {STATUS[status]}"


def monitoring_rows(company, criteria, scores, findings, previous, day) -> list[dict]:
    """Entries for one monitoring check: companies and criteria in Breach or Watch on that day.

    scores: {criterion id: score}; findings: this company's findings; previous: {criterion id: last status before day}.
    """
    rows = []
    for c in criteria:
        score = scores.get(c["id"])
        state = rules.evaluate(score, c)["state"]
        if state not in ("breach", "watch"):
            continue
        pair = [f for f in findings if f["criterion_id"] == c["id"]]
        current_summary = (score or {}).get("summary")
        rows.append({
            "day": day.isoformat(), "origin": "monitoring", "holding_id": company["id"], "criterion_id": c["id"],
            "issuer": company["name"], "isin": company.get("isin"), "criterion": c["label"], "status": state,
            "change": change(previous.get(c["id"]), state), "severity": _severity(pair), "summary": current_summary,
            "sources": _sources(pair),
        })
    return rows


def provider_rows(alerts, companies, criteria, day) -> list[dict]:
    by_ticker = {h.get("ticker") or h["name"]: h for h in companies}
    labels = {c["id"]: c["label"] for c in criteria}
    rows = []
    for a in alerts:
        h = next((by_ticker[t] for t in a.get("tickers") or [] if t in by_ticker), None)
        if h is None:
            continue
        rows.append({
            "day": day.isoformat(), "origin": "provider", "holding_id": h["id"], "criterion_id": None,
            "issuer": h["name"], "isin": h.get("isin"), "status": "provider", "change": "New",
            "criterion": ", ".join(labels[i] for i in a.get("criteria") or [] if i in labels) or None,
            "severity": a.get("severity"), "summary": a.get("title"), "provider_alert_id": a["id"],
            "sources": [{"url": a["url"], "title": a["title"]}] if a.get("url") else [],
        })
    return rows


def period(choice, start=None, end=None, today_=None):
    today_ = today_ or today()
    if choice == "7":
        return today_ - timedelta(days=6), today_
    if choice == "30":
        return today_ - timedelta(days=29), today_
    return start or today_, end or start or today_


def select(rows, first, last, companies=(), criteria=()) -> list[dict]:
    return [r for r in rows if first.isoformat() <= r["day"] <= last.isoformat()
            and (not companies or r["holding_id"] in companies)
            and (not criteria or r["criterion_id"] in criteria)]


def day_label(day: str, today_=None) -> str:
    today_ = today_ or today()
    d = date.fromisoformat(day)
    if d == today_:
        return "Today"
    if d == today_ - timedelta(days=1):
        return "Yesterday"
    return f"{d.day} {d.strftime('%b %Y')}"


def by_day(rows) -> list[tuple[str, dict]]:
    """[(day, {"breach": [card], "watch": [card]})], newest first. A card is one company with its entries."""
    days = {}
    for r in rows:
        days.setdefault(r["day"], []).append(r)
    out = []
    for day in sorted(days, reverse=True):
        entries = days[day]
        breached = {r["holding_id"] for r in entries if r["status"] == "breach"}
        boxes = {"breach": {}, "watch": {}}
        for r in entries:
            box = "breach" if r["holding_id"] in breached else "watch"
            card = boxes[box].setdefault(r["holding_id"], {"issuer": r["issuer"], "holding_id": r["holding_id"], "entries": []})
            card["entries"].append(r)
        out.append((day, {k: sorted(v.values(), key=lambda c: c["issuer"]) for k, v in boxes.items()}))
    return out


COLUMNS = ["Date", "Issuer", "ISIN", "Criterion", "Status", "Change", "Severity", "Summary",
           "Source link 1", "Source link 2", "Source link 3", "Origin"]
WIDTHS = [12, 28, 15, 28, 18, 20, 11, 70, 40, 40, 40, 22]


def to_xlsx(rows) -> bytes:
    """One row per company and criterion per date. Bold header, sized columns, clickable links."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Alert log"
    ws.append(COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.freeze_panes = "A2"
    for r in sorted(rows, key=lambda r: (r["day"], r["issuer"], r.get("criterion") or ""), reverse=False):
        links = [s["url"] for s in r.get("sources") or []][:MAX_SOURCES]
        ws.append([date.fromisoformat(r["day"]), r["issuer"], r.get("isin") or "", r.get("criterion") or "",
                   STATUS[r["status"]], r.get("change") or "", (r.get("severity") or "").capitalize(),
                   r.get("summary") or "", *(links + [""] * (MAX_SOURCES - len(links))), ORIGINS[r["origin"]]])
        row = ws.max_row
        ws.cell(row, 1).number_format = "yyyy-mm-dd"
        ws.cell(row, 8).alignment = Alignment(wrap_text=True, vertical="top")
        for i, url in enumerate(links):
            cell = ws.cell(row, 9 + i)
            if url.startswith(("http://", "https://")):
                cell.hyperlink = url
                cell.style = "Hyperlink"
    for i, width in enumerate(WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def backfill_rows(holdings, criteria, scores, findings, alerts) -> list[dict]:
    """Entries for results that existed before the log: dated at their last monitoring check or import."""
    active = [c for c in criteria if c["active"]]
    rows = []
    for h in holdings:
        checked = {c["id"]: (scores.get((h["id"], c["id"])) or {}).get("monitor_checked") for c in active}
        for day in sorted({d for d in checked.values() if d}):
            mine = [c for c in active if checked[c["id"]] == day]
            rows += monitoring_rows(h, mine, {c["id"]: scores.get((h["id"], c["id"])) for c in mine},
                                    [f for f in findings if f["holding_id"] == h["id"]], {}, date.fromisoformat(day))
    for a in alerts:
        if a.get("origin") == "reprisk":
            day = date.fromisoformat((a.get("created_at") or a.get("date") or today().isoformat())[:10])
            rows += provider_rows([a], holdings, criteria, day)
    return rows
