"""Language preferences for future subscription downloads, independent of UI locale."""
from providers.catalog import normalize_content_language


def subscription_content_languages(entry, defaults, preferences=None):
    values = (preferences or {}).get(str(entry.get("base_slug") or ""), defaults)
    selected = [normalize_content_language(value) for value in values]
    return list(dict.fromkeys(value for value in selected if value)) or list(defaults)
