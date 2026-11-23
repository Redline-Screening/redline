from pathlib import Path

import pandas as pd
import streamlit as st

from redline import db, importers, ui

SAMPLE = Path(__file__).resolve().parent.parent / "sample" / "universe.csv"
LABELS = {
    "name": "Company", "ticker": "Ticker", "isin": "ISIN", "weight": "Weight %", "ytd": "YTD %",
    "r1y": "1Y %", "country": "Country", "sector": "Sector", "type": "Type",
}

ui.page_header("Investment Universe", "Holdings and prospects subject to screening.")
ui.show_notice()

state = st.session_state
state.setdefault("universe_version", 0)
version = state.universe_version


def saved(message: str) -> None:
    state.universe_version += 1
    ui.set_notice(message)
    st.rerun()


try:
    companies = db.holdings()
except db.DataError as e:
    st.error(str(e))
    st.stop()


def upload_panel() -> None:
    st.caption("Only the company name is required. Recognised columns: name, ticker, isin, weight, ytd, 1y, "
               "country, sector, type. Existing companies are updated by ISIN, ticker or name.")
    file = st.file_uploader("CSV file", type=["csv", "txt"], max_upload_size=5, key=f"universe-file-{version}")
    if file is None:
        st.download_button("Download sample file", SAMPLE.read_bytes(), "universe.csv", "text/csv")
        return
    try:
        plan = importers.plan_universe_import(importers.read_table(importers.decode(file.getvalue())), companies)
    except importers.ImportProblem as e:
        st.error(str(e))
        return
    rows = plan["rows"]
    count = {a: sum(r["action"] == a for r in rows) for a in ("Add", "Update", "Skip")}
    st.dataframe(
        pd.DataFrame([
            {"Row": r["row"], "Action": r["action"],
             **{LABELS[f]: r["data"].get(f) for f in importers.FIELDS if f in plan["mapping"]},
             "Note": r["note"]}
            for r in rows
        ]),
        hide_index=True,
        placeholder="",
    )
    total = sum(r["weight"] or 0 for r in plan["records"] if r["type"] == "holding")
    st.caption(f"{count['Add']} to add, {count['Update']} to update, {count['Skip']} skipped. "
               f"Weight of holdings in this file: {total:.2f}%.")
    if 0 < total <= 1.5:
        st.warning("Weights appear to be fractions. Redline expects percentages, for example 12 for 12%.")
    elif total > 100.5:
        st.warning("Weights in this file exceed 100%.")
    if st.button("Import", type="primary", disabled=not plan["records"]):
        try:
            db.save_holdings(plan["records"])
        except db.DataError as e:
            st.error(str(e))
        else:
            saved(f"Companies added: {count['Add']}. Updated: {count['Update']}.")


def add_panel() -> None:
    with st.form(f"add-company-{version}", border=False):
        a, b, c = st.columns(3)
        name = a.text_input("Company")
        ticker = b.text_input("Ticker")
        isin = c.text_input("ISIN")
        a, b, _ = st.columns(3)
        weight = a.number_input("Weight %", min_value=0.0, max_value=100.0, step=0.1)
        kind = b.selectbox("Type", ["holding", "prospect"], format_func=str.capitalize)
        if not st.form_submit_button("Add company"):
            return
    name, ticker, isin = name.strip(), ticker.strip().upper(), isin.strip().upper().replace(" ", "")
    if not name:
        st.error("Enter a company name.")
    elif isin and not importers.valid_isin(isin):
        st.error("The ISIN is not valid.")
    elif importers.find_company(companies, isin=isin, ticker=ticker, name=name):
        st.error("This company is already in the universe.")
    else:
        try:
            db.save_holdings([{"name": name, "ticker": ticker or None, "isin": isin or None,
                               "weight": weight, "type": kind}])
        except db.DataError as e:
            st.error(str(e))
        else:
            saved("Company added.")


@st.dialog("Remove companies")
def confirm(changed: list[dict], removed: list[str]) -> None:
    st.write(f"Companies to remove: {len(removed)}. Their screening results will also be deleted permanently.")
    if st.button("Remove", type="primary"):
        apply(changed, removed)


def apply(changed: list[dict], removed: list[str]) -> None:
    try:
        db.save_holdings(changed)
        db.delete_holdings(removed)
    except db.DataError as e:
        st.error(str(e))
    else:
        saved(f"Companies updated: {len(changed)}. Removed: {len(removed)}.")


def table_panel() -> None:
    kind = st.segmented_control("Show", ["holding", "prospect"], default="holding", required=True,
                                format_func={"holding": "Holdings", "prospect": "Prospects"}.get,
                                label_visibility="collapsed")
    shown = [c for c in companies if c["type"] == kind]
    if not shown:
        st.caption("No companies of this type.")
        return
    frame = pd.DataFrame(shown, columns=["id", *importers.FIELDS])
    for f in importers.NUMERIC:
        frame[f] = pd.to_numeric(frame[f]).astype(float)
    for f in ("ticker", "isin", "country", "sector"):
        frame[f] = frame[f].astype("string")
    frame["remove"] = False
    number = lambda label: st.column_config.NumberColumn(label, format="%.2f")  # noqa: E731
    edited = st.data_editor(
        frame,
        hide_index=True,
        placeholder="",
        key=f"universe-table-{version}-{kind}",
        column_order=[*importers.FIELDS, "remove"],
        column_config={
            **{f: LABELS[f] for f in ("ticker", "isin", "country", "sector")},
            "name": st.column_config.TextColumn("Company", required=True),
            "weight": st.column_config.NumberColumn("Weight %", format="%.2f", min_value=0, max_value=100),
            "ytd": number("YTD %"),
            "r1y": number("1Y %"),
            "type": st.column_config.SelectboxColumn("Type", options=["holding", "prospect"], required=True),
            "remove": st.column_config.CheckboxColumn("Remove"),
        },
    )
    rows = edited.astype(object).where(edited.notna(), None).to_dict("records")
    try:
        changed, removed = importers.diff_edits(shown, rows)
    except importers.ImportProblem as e:
        st.error(str(e))
        return
    if st.button("Save changes", type="primary", disabled=not (changed or removed)):
        if removed:
            confirm(changed, removed)
        else:
            apply(changed, removed)


if companies:
    held = [c for c in companies if c["type"] == "holding"]
    a, b, c = st.columns(3)
    a.metric("Holdings", len(held), border=True)
    b.metric("Weight of holdings", f"{sum(h['weight'] or 0 for h in held):.2f}%", border=True)
    c.metric("Prospects", len(companies) - len(held), border=True)
    with st.container(border=True, key="panel-universe"):
        table_panel()

with st.container(border=True, key="panel-add"):
    upload_tab, add_tab = st.tabs(["Upload CSV", "Add company"])
    with upload_tab:
        upload_panel()
    with add_tab:
        add_panel()

if companies:
    ui.next_step("views/criteria.py", "Exclusion Criteria")
