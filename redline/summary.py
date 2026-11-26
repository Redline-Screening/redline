"""Status summary per company and criterion: a short Haiku call without web search,
based only on the saved findings and the revenue source. No Streamlit import."""
import hashlib
import json
from datetime import date

from redline import evidence, rules
from redline.evidence import EVIDENCE, INVOLVEMENT, LEGAL

MODEL = "claude-haiku-5-5"
VERSION = "2"           # part of the key: a new version regenerates all summaries
MAX_WORDS = 60
ATTEMPTS = 2
# Internal terms that do not belong in a summary for investors.
SYSTEM_TERMS = ("controversy status", "controversy level", "status driven", "driven by", "incident level", "status driver",
                "reasons:", "criterion", "exposure kind", "evaluate", "watch threshold (")
PRICE = (0.10, 0.50)    # US dollars per million tokens, input and output


def state_key(score, findings, criterion) -> str:
    """Identifies what a summary describes: status, open findings and figures."""
    parts = [VERSION, rules.evaluate(score, criterion)["state"], str((score or {}).get("exposure")), str((score or {}).get("exposure_kind")),
             str((score or {}).get("exposure_sourced")), str((score or {}).get("likelihood")),
             *sorted(f"{f['id']}:{f['severity']}" for f in findings if f["status"] == "open")]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def is_current(score, findings, criterion) -> bool:
    return bool(score and score.get("summary") and score.get("summary_key") == state_key(score, findings, criterion))


def needed(score, criterion) -> bool:
    return rules.evaluate(score, criterion)["state"] in ("breach", "watch")


def drivers(score, criterion) -> list[str]:
    """The actual causes of the status, in words."""
    result, score = rules.evaluate(score, criterion), score or {}
    level, out = rules.controversy_level(score), []
    for reason in result["reasons"]:
        if reason == "Revenue":
            out.append(f"a revenue share of {score['exposure']}% from a source, above the limit of {criterion['threshold']}%")
        elif reason == "Controversy":
            out.append("severe incidents" if level == "severe" else f"{level}-severity incidents")
        elif reason == "Unsourced estimate":
            out.append(f"an unsourced revenue estimate of {score['exposure']}%, above the limit of {criterion['threshold']}%")
        elif reason == "Likelihood":
            out.append(f"a likelihood of increase of {score['likelihood']:.0f} out of 100")
    return out


def build_prompt(company, criterion, score, findings) -> str:
    result = rules.evaluate(score, criterion)
    label = rules.LABELS[result["state"]]
    lines = [f"Company: {company['name']}", f"Exclusion: {criterion['label']}",
             f"Status: {label}, caused by: {'; '.join(drivers(score, criterion)) or 'no single cause'}"]
    if rules.uses_revenue(criterion) and (score or {}).get("exposure") is not None:
        kind = rules.revenue_source(score)
        note = " This estimate has no source and is not a cause of a breach." if kind == "Unsourced estimate" else ""
        lines.append(f"Revenue share: {score['exposure']}% ({kind}); limit {criterion['threshold']}%.{note}")
    lines.append("Open findings:")
    for f in sorted((f for f in findings if f["status"] == "open"), key=lambda f: -rules.LEVELS.index(f["severity"])):
        roles = ", ".join(x for x in (INVOLVEMENT.get(f.get("involvement") or ""), EVIDENCE.get(f.get("evidence") or ""),
                                      LEGAL.get(f.get("legal_status") or "")) if x) or "not classified"
        lines.append(f"- [{f['severity']}] {f['title']} ({f.get('date') or 'date unknown'}; {roles}): {f['summary']}")
    return (f"Write a status summary for an investor. Use only the facts below. Start with \"{label} because of\" and the cause "
            "given in the status line, then the company's role and the strongest evidence. Two or three sentences, at most 50 words, "
            "in plain professional language. Mention an unsourced revenue estimate only as an unsourced estimate, never as the cause "
            "of a breach. Do not use internal terms such as status, controversy level or driven by, do not name newspapers or other "
            "outlets, and do not describe sources or your reasoning.\n\n" + "\n".join(lines) +
            '\n\nReply with only one JSON object: {"summary": string}')


def acceptable(text, score, criterion) -> bool:
    """Starts with the actual status, is short and uses no internal terms."""
    label = rules.LABELS[rules.evaluate(score, criterion)["state"]]
    lowered = text.lower()
    return (text.startswith(f"{label} because") and len(text.split()) <= MAX_WORDS
            and not any(t in lowered for t in SYSTEM_TERMS))


def generate(client, company, criterion, score, findings):
    """(summary or None, input tokens, output tokens, cost). Never raises for API problems."""
    try:
        reply = client.messages.create(model=MODEL, max_tokens=2000, output_config={"effort": "low"},
                                       messages=[{"role": "user", "content": build_prompt(company, criterion, score, findings)}])
    except Exception:
        return None, 0, 0, None
    u = reply.usage
    tokens_in = u.input_tokens + (u.cache_creation_input_tokens or 0) + (u.cache_read_input_tokens or 0)
    cost = round((tokens_in * PRICE[0] + u.output_tokens * PRICE[1]) / 1e6, 6)
    text = "".join(b.text for b in reply.content if b.type == "text")
    try:
        value = json.loads(text[text.find("{"): text.rfind("}") + 1])["summary"]
    except (ValueError, KeyError, TypeError):
        value = None
    cleaned = evidence.clean_text("Summary", str(value or "").strip()[:600], []) if reply.stop_reason == "end_turn" else None
    usable = cleaned and acceptable(cleaned[1], score, criterion)
    return (cleaned[1] if usable else None), tokens_in, u.output_tokens, cost


def refresh(sb, client, company, criterion) -> str | None:
    """Regenerates the summary of one company and criterion if the stored one no longer matches.

    Returns the summary, or None when none is needed or possible. Never raises for AI problems.
    """
    pair = {"holding_id": company["id"], "criterion_id": criterion["id"]}
    rows = sb.table("scores").select("*").eq("holding_id", pair["holding_id"]).eq("criterion_id", pair["criterion_id"]).execute().data
    if not rows:
        return None
    score = rows[0]
    findings = sb.table("findings").select("*").eq("holding_id", pair["holding_id"]).eq("criterion_id", pair["criterion_id"]).execute().data
    if not needed(score, criterion) or is_current(score, findings, criterion) or client is None:
        return score.get("summary") if is_current(score, findings, criterion) else None
    if not sb.rpc("can_summarize").execute().data:
        return None
    text = None
    for _ in range(ATTEMPTS):      # one more attempt if the first summary is not acceptable
        text, tokens_in, tokens_out, cost = generate(client, company, criterion, score, findings)
        if tokens_in or tokens_out:
            sb.rpc("log_ai_summary", {"p_model": MODEL, "p_input": tokens_in, "p_output": tokens_out, "p_cost": cost}).execute()
        if text or not (tokens_in or tokens_out):
            break
    if text:
        sb.table("scores").update({"summary": text, "summary_date": date.today().isoformat(),
                                   "summary_key": state_key(score, findings, criterion)}) \
            .eq("holding_id", pair["holding_id"]).eq("criterion_id", pair["criterion_id"]).execute()
    return text
