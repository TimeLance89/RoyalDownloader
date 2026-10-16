"""Pure identity claiming and stable interleaving for series catalog entries."""

from providers.models import FilmpalastSeriesResult


def claim_identity(identity: tuple, claimed: set[tuple]) -> bool:
    """Reserve an identity; return whether it is already visible."""
    if identity in claimed:
        return True
    if len(identity) != 3 or identity[0] != "series":
        claimed.add(identity)
        return False

    _kind, title_key, year = identity
    unknown = ("series", title_key, "")
    known = {
        item for item in claimed
        if len(item) == 3 and item[0] == "series" and item[1] == title_key and item[2]
    }
    if year and unknown in claimed:
        # Refine the first yearless match while keeping later remakes distinct.
        claimed.remove(unknown)
        claimed.add(identity)
        return True
    if not year and len(known) == 1:
        return True
    claimed.add(identity)
    return False


def interleave_lists(
    *lists: list[FilmpalastSeriesResult],
) -> list[FilmpalastSeriesResult]:
    """Interleave signal lists while removing duplicate source identities."""
    merged: list[FilmpalastSeriesResult] = []
    seen: set[str] = set()
    longest = max((len(items) for items in lists), default=0)
    for index in range(longest):
        for items in lists:
            if index >= len(items):
                continue
            result = items[index]
            key = str(result.base_slug or result.sample_slug or result.sample_url or result.title)
            if key in seen:
                continue
            seen.add(key)
            merged.append(result)
    return merged
