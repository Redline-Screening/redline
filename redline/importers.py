"""Reading CSV files and matching rows to companies. No Streamlit import."""
import csv
import io
import math
import re
import unicodedata
import uuid

MAX_ROWS = 2000
FIELDS = ("name", "ticker", "isin", "weight", "ytd", "r1y", "country", "sector", "type")
NUMERIC = ("weight", "ytd", "r1y")

# Normalised column names accepted for each field, in order of preference.
ALIASES = {
    "isin": ["isin", "isin code"],
    "ticker": ["ticker", "symbol", "ticker symbol"],
    "name": ["name", "company", "company name", "security name", "security", "issuer", "issuer name", "holding"],
    "weight": ["weight", "weight %", "wgt", "portfolio weight", "% of fund", "% of portfolio", "% weight"],
    "ytd": ["ytd", "ytd %", "ytd return", "return ytd"],
    "r1y": ["1y", "1y %", "r1y", "1y return", "return 1y", "1 year", "1 year return", "12m", "12m return"],
    "country": ["country", "domicile"],
    "sector": ["sector", "gics sector", "industry"],
    "type": ["type", "holding type"],
}


class ImportProblem(Exception):
    """Message suitable for display."""


def decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ImportProblem("The file encoding is not supported. Save the file as CSV UTF-8.")


def read_table(text: str) -> list[dict]:
    """Rows as dictionaries. The delimiter is taken from the header line."""
    text = text.strip("\r\n")
    if not text.strip():
        raise ImportProblem("The file is empty.")
    header = text.splitlines()[0]
    delimiter = max(",;\t", key=header.count)
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delimiter) if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise ImportProblem("The file needs a header row and at least one company.")
    if len(rows) - 1 > MAX_ROWS:
        raise ImportProblem(f"The file has more than {MAX_ROWS} rows.")
    names = [c.strip() for c in rows[0]]
    return [{n: (r[i].strip() if i < len(r) else "") for i, n in enumerate(names) if n} for r in rows[1:]]


def _norm_column(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[_\-().]", " ", name.lower())).strip()


def map_columns(columns, aliases=ALIASES) -> dict:
    """Field -> column name."""
    normal = {}
    for c in columns:
        normal.setdefault(_norm_column(c), c)
    mapping = {}
    for field, names in aliases.items():
        for alias in names:
            if alias in normal:
                mapping[field] = normal[alias]
                break
    return mapping


def parse_number(value) -> float | None:
    """Percentages with a decimal point or comma: 2.5, 2,5, 1'234.5, 1.234,5 %."""
    if value is None:
        return None
    s = re.sub(r"[\s%'’  ]", "", str(value)).replace("−", "-")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif s.count(",") == 1:
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        number = float(s)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def valid_isin(isin: str) -> bool:
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", isin):
        return False
    digits = "".join(str(int(c, 36)) for c in isin)
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d) * (2 if i % 2 else 1)
        total += n // 10 + n % 10
    return total % 10 == 0


def norm_name(name) -> str:
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def find_company(companies, *, isin="", ticker="", name=""):
    """ISIN, then ticker, then exact normalised name.

    Two different ISINs are never treated as the same company.
    """
    if isin:
        for c in companies:
            if c.get("isin") == isin:
                return c
    free = [c for c in companies if not (isin and c.get("isin"))]
    if ticker:
        hits = [c for c in free if (c.get("ticker") or "").upper() == ticker.upper()]
        if len(hits) == 1:
            return hits[0]
    key = norm_name(name)
    if key:
        hits = [c for c in free if norm_name(c.get("name")) == key
                and not (ticker and c.get("ticker") and c["ticker"].upper() != ticker.upper())]
        if len(hits) == 1:
            return hits[0]
    return None


def plan_universe_import(rows: list[dict], existing: list[dict]) -> dict:
    """Decide what each row does. Returns {mapping, rows: [{row, action, note, data}], records}.

    records are complete rows with ids, ready for a single upsert.
    """
    mapping = map_columns(rows[0].keys())
    if "name" not in mapping:
        raise ImportProblem("No company name column found. Use a column named name, company, security or issuer.")
    companies = [dict(c) for c in existing]
    known = {c["id"] for c in existing}
    seen, plan, records = {}, [], []
    for i, raw in enumerate(rows, start=2):
        notes = []
        get = lambda f: raw.get(mapping.get(f, ""), "").strip()  # noqa: E731
        name, ticker, isin = get("name"), get("ticker").upper(), get("isin").upper().replace(" ", "")
        if not name:
            plan.append({"row": i, "action": "Skip", "note": "No company name", "data": {}})
            continue
        if isin and not valid_isin(isin):
            notes.append(f"Invalid ISIN {isin} left out")
            isin = ""
        data = {"name": name}
        if ticker:
            data["ticker"] = ticker
        if isin:
            data["isin"] = isin
        for f in NUMERIC:
            if get(f):
                number = parse_number(get(f))
                if number is None:
                    notes.append(f"{f} is not a number")
                else:
                    data[f] = number
        for f in ("country", "sector"):
            if get(f):
                data[f] = get(f)
        if get("type"):
            data["type"] = "prospect" if get("type").lower().startswith("pros") else "holding"
        if data.get("weight", 0) > 100:
            notes.append("Weight above 100%")

        match = find_company(companies, isin=isin, ticker=ticker, name=name)
        if match and match["id"] in seen:
            plan.append({"row": i, "action": "Skip", "note": f"Duplicate of row {seen[match['id']]}", "data": data})
            continue
        if match:
            match.update(data)
            record = match
        else:
            record = {"id": str(uuid.uuid4()), "weight": 0, "type": "holding", **data}
            companies.append(record)
        seen[record["id"]] = i
        records.append({"id": record["id"], **{f: record.get(f) for f in FIELDS}})
        plan.append({"row": i, "action": "Update" if record["id"] in known else "Add", "note": "; ".join(notes), "data": data})
    return {"mapping": mapping, "rows": plan, "records": records}


def _clean(value):
    if value is None or (isinstance(value, float) and math.isnan(value)) or value != value:
        return None
    if isinstance(value, str):
        return value.strip() or None
    return value


def diff_edits(before: list[dict], after: list[dict]) -> tuple[list[dict], list[str]]:
    """Changed records and removed ids from the edited table. Raises on invalid values."""
    old = {c["id"]: c for c in before}
    changed, removed = [], []
    for row in after:
        original = old[row["id"]]
        if row.get("remove"):
            removed.append(row["id"])
            continue
        record = {f: _clean(row.get(f, original.get(f))) for f in FIELDS}
        if not record["name"]:
            raise ImportProblem("A company name is required.")
        for f in ("ticker", "isin"):
            record[f] = record[f].upper() if record[f] else None
        if record["isin"] and not valid_isin(record["isin"]):
            raise ImportProblem(f"ISIN {record['isin']} is not valid.")
        record["weight"] = record["weight"] or 0
        if any(record[f] != _clean(original.get(f)) for f in FIELDS):
            changed.append({"id": row["id"], **record})
    return changed, removed
