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


def _all(table: str, order: str, desc: bool = False) -> list[dict]:
    rows = []
    while True:
        page = _run(
            auth.client().table(table).select("*")
            .order(order, desc=desc).order("id")
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
