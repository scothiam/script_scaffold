from collections import Counter
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def format_price(price: float | None, currency: str | None = None) -> str:
    """Format a price for display.

    When currency is provided it is prepended (e.g. "CAD $862.83").
    Without currency, returns bare "$862.83".
    """
    if price is None:
        return "—"
    amount = f"${price:,.2f}"
    return f"{currency} {amount}" if currency else amount


def format_date(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return dt.strftime("%Y-%m-%d")


def vote_with_confidence(
    extracted_list: list[dict],
    normalise_fn=None,
    min_confidence: dict[str, int] | None = None,
) -> tuple[dict, dict[str, int]]:
    """Majority-vote across per-result dicts.

    Counts normalised values so equivalent representations (e.g. "448.0 GB/s"
    vs "448 GB/s") are the same vote. Fields that don't reach the required
    confidence threshold are excluded from the output.

    Args:
        extracted_list:  List of dicts, one per source, each mapping field → value.
        normalise_fn:    Optional callable(field, value) → str | None that normalises
                         values before counting. Returning None skips the value.
                         Defaults to str(value).strip().lower().
        min_confidence:  Minimum vote count required per field. Defaults to 1 for all.

    Returns:
        (specs, confidence) where specs[field] is the winning original value and
        confidence[field] is how many sources agreed on it.
    """
    if normalise_fn is None:
        def normalise_fn(field, value):  # noqa: F811
            return str(value).strip().lower() if value is not None else None

    min_conf = min_confidence or {}

    votes: dict[str, Counter] = {}
    norm_to_orig: dict[str, dict[str, str]] = {}

    for extracted in extracted_list:
        for field, value in extracted.items():
            norm = normalise_fn(field, value)
            if norm is None:
                continue
            if field not in votes:
                votes[field] = Counter()
                norm_to_orig[field] = {}
            votes[field][norm] += 1
            norm_to_orig[field].setdefault(norm, str(value))

    specs: dict = {}
    confidence: dict[str, int] = {}

    for field, counter in votes.items():
        winning_norm, count = counter.most_common(1)[0]
        required = min_conf.get(field, 1)
        if count < required:
            continue
        confidence[field] = count
        specs[field] = norm_to_orig[field][winning_norm]

    return specs, confidence
