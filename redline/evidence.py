"""Limits that the app enforces on AI findings and estimates. No Streamlit import."""
import re
from datetime import date
from urllib.parse import urlsplit

from redline.rules import LEVELS

INVOLVEMENT = {"company": "Company or subsidiary", "supplier": "Supplier of the company",
               "partner": "Partner or investee", "unclear": "Involvement unclear"}
EVIDENCE = {"proven": "Proven", "alleged": "Alleged"}
LEGAL = {"none": "No legal case", "open": "Case open", "settled": "Case settled", "dismissed": "Case dismissed",
         "against": "Ruled against", "unclear": "Legal status unclear"}


def rank(level) -> int:
    return LEVELS.index(level) if level in LEVELS else 0


def max_severity(involvement, evidence, legal) -> str:
    """Highest severity a finding may have. The lowest matching limit applies."""
    if legal == "dismissed":
        return "low"
    proven = evidence == "proven" or (legal == "against" and involvement == "company")
    if involvement == "company":
        if legal == "settled" and not proven:
            return "medium"
        if legal == "open" or not proven:
            return "high"
        return "severe"
    if involvement in ("supplier", "partner"):
        return "high" if proven else "medium"
    return "medium"


def capped(severity, involvement, evidence, legal) -> str:
    return min(severity, max_severity(involvement, evidence, legal), key=rank)


# ---------- revenue ----------

def _numbers(text) -> list[float]:
    """Numbers in a quote: 12.5, 12,5 and 1,234.5 (a comma before exactly three digits separates thousands)."""
    out = []
    for m in re.findall(r"\d+(?:[.,]\d+)*", str(text)):
        m = re.sub(r",(?=\d{3}(?:\D|$))", "", m).replace(",", ".")
        try:
            out.append(float(m))
        except ValueError:
            continue
    return out


def _positive(value):
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0
    return float(value) if ok else None


def exposure_is_sourced(exposure, source, links) -> bool:
    """True when a linked source gives the share, or both revenues of the same year.

    The quote is checked for the figure. Whether the page contains the quote cannot be checked.
    """
    if not isinstance(source, dict) or not links:
        return False
    quote = str(source.get("quote") or "").strip()
    if source.get("kind") == "stated_share":
        return any(abs(n - exposure) <= 0.051 for n in _numbers(quote))
    if source.get("kind") == "calculated":
        part, total = _positive(source.get("activity_revenue")), _positive(source.get("total_revenue"))
        year, total_year = source.get("activity_year"), source.get("total_year")
        if part is None or not total or not year or year != total_year or not _numbers(quote):
            return False
        return abs(part / total * 100 - exposure) <= max(0.051, exposure * 0.05)
    return False


# ---------- outlets ----------

OUTLETS = {
    "Washington Post": "washingtonpost.com", "WaPo": "washingtonpost.com", "New York Times": "nytimes.com", "NYT": "nytimes.com",
    "Wall Street Journal": "wsj.com", "WSJ": "wsj.com", "Financial Times": "ft.com", "Reuters": "reuters.com",
    "Bloomberg": "bloomberg.com", "Associated Press": "apnews.com", "AP News": "apnews.com", "BBC": "bbc.co", "CNN": "cnn.com",
    "CNBC": "cnbc.com", "NBC News": "nbcnews.com", "CBS News": "cbsnews.com", "ABC News": "abcnews", "Fox News": "foxnews.com",
    "NPR": "npr.org", "The Guardian": "theguardian.com", "The Economist": "economist.com", "Forbes": "forbes.com",
    "Politico": "politico", "Axios": "axios.com", "The Verge": "theverge.com", "WIRED": "wired.com", "Wired": "wired.com",
    "TechCrunch": "techcrunch.com", "Ars Technica": "arstechnica.com", "Technology Review": "technologyreview.com",
    "The Intercept": "theintercept.com", "Business Insider": "businessinsider.com", "ProPublica": "propublica.org",
    "404 Media": "404media.co", "+972 Magazine": "972mag.com", "Al Jazeera": "aljazeera.com", "Haaretz": "haaretz.com",
    "Times of Israel": "timesofisrael.com", "Der Spiegel": "spiegel.de", "Le Monde": "lemonde.fr", "Handelsblatt": "handelsblatt.com",
    "NZZ": "nzz.ch", "Nikkei": "nikkei.com", "South China Morning Post": "scmp.com", "Defense News": "defensenews.com",
    "DefenseScoop": "defensescoop.com", "Breaking Defense": "breakingdefense.com", "Defense One": "defenseone.com",
    "Army Times": "armytimes.com", "Military Times": "militarytimes.com", "USA Today": "usatoday.com", "Los Angeles Times": "latimes.com",
    "The Independent": "independent.co.uk", "The Telegraph": "telegraph.co.uk", "Deutsche Welle": "dw.com", "Tagesschau": "tagesschau.de",
}
_SENTENCE = re.compile(
    r"(?<=[.!?])(?<!\.[A-Z]\.)(?<!\b[A-Z]\.)(?<!Inc\.)(?<!Corp\.)(?<!Ltd\.)(?<!Co\.)(?<!Sept\.)(?<!vs\.)(?<! v\.)(?<!No\.)\s+")


def unlinked_outlets(text, sources) -> list[str]:
    hosts = [urlsplit(s["url"]).netloc.lower() for s in sources]
    return [name for name, domain in OUTLETS.items()
            if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", str(text)) and not any(domain in h for h in hosts)]


def keeps_first_sentence(summary, sources) -> bool:
    """False when the first sentence, which states the incident or allegation, names an unlinked outlet."""
    first = _SENTENCE.split(str(summary).strip(), maxsplit=1)[0]
    return not unlinked_outlets(first, sources)


def clean_text(title, summary, sources) -> tuple[str, str] | None:
    """Removes sentences that name an outlet without a link. None: the text cannot be used."""
    if not title or unlinked_outlets(title, sources):
        return None
    kept = " ".join(s for s in _SENTENCE.split(summary) if not unlinked_outlets(s, sources)).strip()
    return (title, kept) if kept else None


# ---------- dates ----------

_MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), start=1)}


def parse_date(value, today) -> tuple[str, str] | None:
    """(ISO date, precision) for YYYY-MM-DD, YYYY-MM or YYYY, not in the future."""
    text = str(value or "").strip()
    m = re.fullmatch(r"(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", text)
    if not m or text > today[:len(text)]:
        return None
    try:
        iso = date(int(m[1]), int(m[2] or 1), int(m[3] or 1)).isoformat()
    except ValueError:
        return None
    return iso, "day" if m[3] else "month" if m[2] else "year"


def reported_month(summary, today) -> tuple[str, str] | None:
    """Month of a report named in a summary, such as 'per a Sept 2026 report'."""
    month = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
    hits = re.findall(rf"\b{month}\s+(\d{{4}})\s+(?:report|article|investigation|story)\b", summary, re.I)
    hits += re.findall(rf"\b(?:report|article|investigation|story)\s+(?:from|of|in|published in)\s+{month}\s+(\d{{4}})\b", summary, re.I)
    found = {f"{year}-{_MONTHS[name.lower()]:02d}" for name, year in hits}
    return parse_date(found.pop(), today) if len(found) == 1 else None
