"""History of pre-investment screenings, decisions and the Excel export. No Streamlit import, no AI calls."""
import io
import re
from datetime import date

from redline import rules, summary

DECISIONS = {"review": "Under review", "prospect": "Added as prospect", "rejected": "Rejected"}
ORDER = {"breach": 0, "watch": 1, "clear": 2, "partial": 3, "na": 4}


def _checked(score) -> str | None:
    score = score or {}
    dates = [(score.get("controversy") or {}).get("checked"), score.get("exposure_date")]
    return max((d for d in dates if d), default=None)


def first_sentence(text) -> str:
    text = str(text or "").strip()
    match = re.match(r"(.+?[.!?])(\s|$)", text)
    return match.group(1) if match else text


def history(holdings, criteria, scores, findings, notes) -> list[dict]:
    """One entry per pre-investment company, newest check first."""
    by_criterion = {c["id"]: c for c in criteria}
    latest_note = {}
    for n in sorted(notes, key=lambda n: n.get("created_at") or ""):
        latest_note[n["holding_id"]] = n
    out = []
    for h in holdings:
        # Marked pre-investment companies, and prospects: those added before the marker existed are not marked.
        if not (h.get("pre_investment") or h["type"] in ("candidate", "prospect")):
            continue
        checked = [(by_criterion[cid], s) for (hid, cid), s in scores.items() if hid == h["id"] and cid in by_criterion
                   and _checked(s)]
        if not checked:
            continue
        results = []
        for c, s in checked:
            pair = [f for f in findings if f["holding_id"] == h["id"] and f["criterion_id"] == c["id"]]
            state = rules.evaluate(s, c)["state"]
            text = s.get("summary") if summary.is_current(s, pair, c) else None
            results.append((ORDER.get(state, 4), state, text, c["label"]))
        results.sort(key=lambda r: r[0])
        worst = results[0][1] if results[0][1] in ("breach", "watch") else "clear"
        note = latest_note.get(h["id"])
        out.append({
            "holding_id": h["id"], "company": h["name"], "isin": h.get("isin") or "",
            "date": max(_checked(s) for _, s in checked), "criteria": ", ".join(sorted(r[3] for r in results)),
            "result": worst, "summary": first_sentence(next((r[2] for r in results if r[2]), "")),
            "decision": h.get("decision") or ("prospect" if h["type"] == "prospect" else "review"),
            "in_universe": h["type"] != "candidate",
            "note": note["text"] if note else "", "note_date": (note.get("created_at") or "")[:10] if note else "",
        })
    return sorted(out, key=lambda r: (r["date"], r["company"]), reverse=True)


def decision_change(company, decision) -> dict:
    """Fields to save for a new decision. "Added as prospect" puts the company in the universe; the others take it out."""
    kind = "prospect" if decision == "prospect" else ("candidate" if company["type"] in ("candidate", "prospect") else company["type"])
    return {**company, "decision": decision, "type": kind, "pre_investment": True}


COLUMNS = ["Date", "Company", "ISIN", "Criteria", "Result", "Summary", "Decision", "Note", "Note date"]
WIDTHS = [12, 30, 15, 36, 10, 70, 18, 50, 12]


def to_xlsx(rows) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Pre-investment"
    ws.append(COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.freeze_panes = "A2"
    for r in rows:
        ws.append([date.fromisoformat(r["date"]), r["company"], r["isin"], r["criteria"], rules.LABELS.get(r["result"], r["result"]),
                   r["summary"], DECISIONS[r["decision"]], r["note"],
                   date.fromisoformat(r["note_date"]) if r["note_date"] else None])
        ws.cell(ws.max_row, 1).number_format = ws.cell(ws.max_row, 9).number_format = "yyyy-mm-dd"
        for col in (6, 8):
            ws.cell(ws.max_row, col).alignment = Alignment(wrap_text=True, vertical="top")
    for i, width in enumerate(WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
