"""Builds data/companies.csv from the constituent tables of Wikipedia index pages (CC BY-SA 4.0).

Usage: download the pages listed in PAGES as HTML into a folder, then
    .venv/bin/python scripts/build_company_list.py <folder>
Only ISINs given by the source and passing the check digit are kept; none are added from elsewhere.
"""
import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from redline.importers import norm_name, valid_isin  # noqa: E402

PAGES = {
    "List_of_S%26P_500_companies": ("S&P 500", "United States"), "FTSE_100_Index": ("FTSE 100", "United Kingdom"),
    "Swiss_Market_Index": ("SMI", "Switzerland"), "SPI_20": ("SMI", "Switzerland"), "DAX": ("DAX", "Germany"),
    "CAC_40": ("CAC 40", "France"), "AEX_index": ("AEX", "Netherlands"), "IBEX_35": ("IBEX 35", "Spain"),
    "FTSE_MIB": ("FTSE MIB", "Italy"), "BEL_20": ("BEL 20", "Belgium"), "EURO_STOXX_50": ("EURO STOXX 50", None),
    "OMX_Stockholm_30": ("OMX Stockholm 30", "Sweden"), "OMX_Copenhagen_25": ("OMX Copenhagen 25", "Denmark"),
    "OMX_Helsinki_25": ("OMX Helsinki 25", "Finland"), "OBX_Index": ("OBX", "Norway"), "PSI-20": ("PSI", "Portugal"),
    "ATX": ("ATX", "Austria"), "ISEQ_20": ("ISEQ 20", "Ireland"),
}


def column(table, *names):
    for c in table.columns:
        label = re.sub(r"\[.*?\]", "", " ".join(map(str, c)) if isinstance(c, tuple) else str(c)).strip().lower()
        if any(label == n or label.startswith(n) for n in names):
            return c
    return None


def ticker_of(value) -> str:
    parts = [p for p in re.split(r"[:\s]+", str(value).strip()) if p]
    return parts[-1] if parts else ""


def build(folder: Path) -> pd.DataFrame:
    rows = {}
    for page, (index, country) in PAGES.items():
        path = folder / f"{page}.html"
        if not path.exists():
            continue
        try:
            tables = pd.read_html(path)
        except ValueError:
            continue
        for t in tables:
            name, ticker = column(t, "company", "security", "name", "constituent"), column(t, "ticker", "symbol")
            if name is None or ticker is None or len(t) < 10 or column(t, "period", "date removed", "removed") is not None:
                continue
            isin, office = column(t, "isin"), column(t, "registered office", "headquarters")
            for _, r in t.iterrows():
                n, tk = str(r[name]).strip(), ticker_of(r[ticker])
                if not n or n == "nan" or not tk or tk.lower() in ("nan", "listed") or len(n) > 80:
                    continue
                i = str(r[isin]).strip().upper() if isin is not None else ""
                c = country or (str(r[office]).split(",")[-1].strip() if office is not None else "")
                old = rows.get(norm_name(n))
                if old:
                    old["isin"] = old["isin"] or (i if valid_isin(i) else "")
                    continue
                rows[norm_name(n)] = {"name": n, "ticker": tk, "isin": i if valid_isin(i) else "", "country": c, "index": index}
    return pd.DataFrame(sorted(rows.values(), key=lambda r: r["name"].lower()))


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "data"
    df = build(Path(sys.argv[1]))
    df.to_csv(out / "companies.csv", index=False)
    (out / "SOURCES.md").write_text(
        f"# Company list\n\n`companies.csv` was built on {date.today().isoformat()} with `scripts/build_company_list.py` from the "
        "constituent tables of these English Wikipedia articles, licensed under CC BY-SA 4.0 "
        "(https://creativecommons.org/licenses/by-sa/4.0/):\n\n"
        + "".join(f"- {idx}: https://en.wikipedia.org/wiki/{p}\n" for p, (idx, _) in PAGES.items())
        + "\nISINs are included only where the source table gives them and the check digit is valid. "
          "Index membership changes; the list is a convenience for searching and is not maintained as reference data.\n")
    print(len(df), "companies,", int((df["isin"] != "").sum()), "with ISIN")
