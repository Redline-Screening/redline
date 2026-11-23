"""All Supabase reads and writes for the signed-in user (row-level security applies)."""
import httpx
from postgrest.exceptions import APIError

from redline import auth

_PAGE = 1000


class DataError(Exception):
    """Message suitable for display."""


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
        _run(auth.client().table("holdings").upsert(records, on_conflict="id"))


def delete_holdings(ids: list[str]) -> None:
    for i in range(0, len(ids), 100):
        _run(auth.client().table("holdings").delete().in_("id", ids[i : i + 100]))


def criteria() -> list[dict]:
    return _all("criteria", "sort")


def save_criteria(records: list[dict]) -> None:
    """Insert or update complete rows in one request: all are saved or none."""
    if records:
        _run(auth.client().table("criteria").upsert(records, on_conflict="id"))


def delete_criteria(ids: list[str]) -> None:
    if ids:
        _run(auth.client().table("criteria").delete().in_("id", ids))


def scores() -> list[dict]:
    return _all("scores", "holding_id", then="criterion_id")


def save_score(record: dict) -> None:
    """Insert or update one score. Columns left out of the record keep their value."""
    _run(auth.client().table("scores").upsert([record], on_conflict="holding_id,criterion_id"))


def save_scores(records: list[dict]) -> None:
    """All records need the same columns. All are saved or none."""
    if records:
        _run(auth.client().table("scores").upsert(records, on_conflict="holding_id,criterion_id"))


def delete_score(holding_id: str, criterion_id: str) -> None:
    _run(auth.client().table("scores").delete().eq("holding_id", holding_id).eq("criterion_id", criterion_id))


def alerts() -> list[dict]:
    return _all("alerts", "date", desc=True)


def add_alerts(records: list[dict]) -> None:
    if records:
        _run(auth.client().table("alerts").insert(records))


def workspace() -> dict:
    rows = _run(auth.client().table("workspaces").select("*"))
    return rows[0] if rows else {}


def save_workspace(fields: dict) -> None:
    """Columns left out keep their value."""
    user = auth.current_user()
    if user is None:
        raise DataError("The session has ended. Sign in again.")
    _run(auth.client().table("workspaces").upsert([{"user_id": user.id, **fields}], on_conflict="user_id"))


def findings() -> list[dict]:
    return _all("findings", "last_seen", desc=True)


def ai_status() -> dict:
    """Remaining AI checks: {user, global, budget, remaining}."""
    return _run(auth.client().rpc("ai_status"))
