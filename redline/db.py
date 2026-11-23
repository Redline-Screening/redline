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
            raise DataError("A company with this ISIN already exists.") from e
        raise DataError(f"The database rejected the request ({e.code}).") from e
    except httpx.HTTPError as e:
        raise DataError("The database is not reachable. Try again shortly.") from e


def holdings() -> list[dict]:
    """All companies, largest weight first."""
    rows = []
    while True:
        page = _run(
            auth.client().table("holdings").select("*")
            .order("weight", desc=True).order("id")
            .range(len(rows), len(rows) + _PAGE - 1)
        )
        rows += page
        if len(page) < _PAGE:
            return rows


def save_holdings(records: list[dict]) -> None:
    """Insert or update complete rows in one request: all are saved or none."""
    if records:
        _run(auth.client().table("holdings").upsert(records, on_conflict="id"))


def delete_holdings(ids: list[str]) -> None:
    for i in range(0, len(ids), 100):
        _run(auth.client().table("holdings").delete().in_("id", ids[i : i + 100]))
