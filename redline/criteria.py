"""Building and editing exclusion criteria. No Streamlit import."""
import re
import uuid

from redline.constants import CONTROVERSY_LIMITS, TEMPLATES

FIELDS = ("key", "label", "description", "threshold", "watch_at", "controversy_limit", "keywords", "active", "sort")


class CriterionProblem(Exception):
    """Message suitable for display."""


def slug(text) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:48].strip("-")


def split_keywords(text) -> list[str]:
    words = [w.strip().lower() for w in re.split(r"[,;\n]", str(text or ""))]
    return list(dict.fromkeys(w for w in words if w))


def _next_sort(existing) -> int:
    return max((c.get("sort") or 0 for c in existing), default=0) + 1


def from_templates(keys, existing) -> list[dict]:
    used = {c.get("key") for c in existing}
    start = _next_sort(existing)
    chosen = [t for t in TEMPLATES if t["key"] in keys and t["key"] not in used]
    return [{"id": str(uuid.uuid4()), **t, "active": True, "sort": start + i} for i, t in enumerate(chosen)]


def _validate(record) -> dict:
    if not record["label"]:
        raise CriterionProblem("A criterion name is required.")
    for field, name in (("threshold", "Revenue limit"), ("watch_at", "Watch level")):
        value = record[field]
        if value is None or value != value or not 0 <= value <= 100:
            raise CriterionProblem(f"{name} must be between 0 and 100.")
    if record["controversy_limit"] not in CONTROVERSY_LIMITS:
        raise CriterionProblem("Select a controversy level.")
    return record


def custom(label, description, threshold, controversy_limit, watch_at, keywords, existing) -> dict:
    label = label.strip()
    key = slug(label)
    if label and not key:
        raise CriterionProblem("The criterion name needs at least one letter or number.")
    if any(c.get("key") == key or c["label"].strip().lower() == label.lower() for c in existing):
        raise CriterionProblem("A criterion with this name already exists.")
    return _validate({
        "id": str(uuid.uuid4()), "key": key, "label": label, "description": description.strip() or None,
        "threshold": threshold, "watch_at": watch_at, "controversy_limit": controversy_limit,
        "keywords": split_keywords(keywords), "active": True, "sort": _next_sort(existing),
    })


def diff_edits(before: list[dict], after: list[dict]) -> tuple[list[dict], list[str]]:
    """Changed records and removed ids from the edited table. keywords arrive as text."""
    old = {c["id"]: c for c in before}
    changed, removed, labels = [], [], set()
    for row in after:
        original = old[row["id"]]
        if row.get("remove"):
            removed.append(row["id"])
            continue
        record = {f: original.get(f) for f in FIELDS}
        record.update(
            label=str(row["label"] or "").strip(),
            description=str(row["description"] or "").strip() or None,
            threshold=row["threshold"], watch_at=row["watch_at"],
            controversy_limit=row["controversy_limit"],
            keywords=split_keywords(row["keywords"]), active=bool(row["active"]),
        )
        _validate(record)
        if record["label"].lower() in labels:
            raise CriterionProblem("Two criteria have the same name.")
        labels.add(record["label"].lower())
        same = dict(original, description=original.get("description") or None,
                    keywords=split_keywords(",".join(original.get("keywords") or [])))
        if any(record[f] != same.get(f) for f in FIELDS):
            changed.append({"id": row["id"], **record})
    return changed, removed
