"""All Supabase reads and writes for the signed-in user (row-level security applies)."""
import httpx
import streamlit as st
from postgrest.exceptions import APIError

from redline import auth, service

_PAGE = 1000


class DataError(Exception):
    """Message suitable for display."""


READ_ONLY = "The demo account is read-only."


def _write(query):
    """The database refuses changes by read-only accounts; this adds a clear message."""
    if st.session_state.get("_read_only"):
        raise DataError(READ_ONLY)
    return _run(query)


def is_read_only() -> bool:
    """Read once per session. Sign-out clears the session."""
    if "_read_only" not in st.session_state:
        rows = _run(auth.client().table("accounts").select("*"))
        st.session_state["_read_only"] = bool(rows and rows[0].get("read_only"))
    return st.session_state["_read_only"]


def _run(query):
    try:
        return query.execute().data
    except APIError as e:
        if e.code == "23505":
            raise DataError("An entry with the same identifier already exists.") from e
        raise DataError(f"The database rejected the request ({e.code}).") from e
    except httpx.HTTPError as e:
        raise DataError("The database is not reachable. Try again shortly.") from e


def _all(table: str, order: str, desc: bool = False, then: str = "id") -> list[dict]:
    rows = []
    while True:
        page = _run(
            auth.client().table(table).select("*")
            .order(order, desc=desc).order(then)
            .range(len(rows), len(rows) + _PAGE - 1)
        )
        rows += page
        if len(page) < _PAGE:
            return rows


def holdings() -> list[dict]:
    """All companies, largest weight first."""
    return _all("holdings", "weight", desc=True)


def save_holdings(records: list[dict]) -> None:
    """Insert or update complete rows in one request: all are saved or none."""
    if records:
        _write(auth.client().table("holdings").upsert(records, on_conflict="id"))


def delete_holdings(ids: list[str]) -> None:
    for i in range(0, len(ids), 100):
        _write(auth.client().table("holdings").delete().in_("id", ids[i : i + 100]))


def criteria() -> list[dict]:
    return _all("criteria", "sort")


def save_criteria(records: list[dict]) -> None:
    """Insert or update complete rows in one request: all are saved or none."""
    if records:
        _write(auth.client().table("criteria").upsert(records, on_conflict="id"))


def delete_criteria(ids: list[str]) -> None:
    if ids:
        _write(auth.client().table("criteria").delete().in_("id", ids))


def scores() -> list[dict]:
    return _all("scores", "holding_id", then="criterion_id")


def save_score(record: dict) -> None:
    """Insert or update one score. Columns left out of the record keep their value."""
    _write(auth.client().table("scores").upsert([record], on_conflict="holding_id,criterion_id"))


def save_scores(records: list[dict]) -> None:
    """All records need the same columns. All are saved or none."""
    if records:
        _write(auth.client().table("scores").upsert(records, on_conflict="holding_id,criterion_id"))


def delete_score(holding_id: str, criterion_id: str) -> None:
    _write(auth.client().table("scores").delete().eq("holding_id", holding_id).eq("criterion_id", criterion_id))


def alerts() -> list[dict]:
    return _all("alerts", "date", desc=True)


def add_alerts(records: list[dict]) -> None:
    if records:
        _write(auth.client().table("alerts").insert(records))


def workspace() -> dict:
    rows = _run(auth.client().table("workspaces").select("*"))
    return rows[0] if rows else {}


def save_workspace(fields: dict) -> None:
    """Columns left out keep their value."""
    user = auth.current_user()
    if user is None:
        raise DataError("The session has ended. Sign in again.")
    _write(auth.client().table("workspaces").upsert([{"user_id": user.id, **fields}], on_conflict="user_id"))


def findings() -> list[dict]:
    return _all("findings", "last_seen", desc=True)


def ai_status() -> dict:
    """Remaining AI checks: {user, global, budget, remaining}."""
    return _run(auth.client().rpc("ai_status"))


def dismiss_finding(finding: dict) -> None:
    if is_read_only():
        raise DataError(READ_ONLY)
    try:
        service.dismiss(auth.client(), finding)
    except (APIError, httpx.HTTPError) as e:
        raise DataError("The finding could not be dismissed completely. Try again.") from e


def refresh_summaries(pairs) -> None:
    """pairs: [(company, criterion)]. Regenerates status summaries after a change; never raises."""
    key = st.secrets.get("ANTHROPIC_API_KEY")
    if not key or is_read_only() or not pairs:
        return
    with st.spinner("Updating status summaries"):
        for company, criterion in pairs:
            service.refresh_summaries(auth.client(), service.claude(key), company, [criterion])
