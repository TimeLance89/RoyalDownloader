"""Concrete episode language evidence shared by subscriptions and detail checks."""

from providers.catalog import normalize_content_language, provider_content_languages

LANGUAGE_EVIDENCE_TTL = 15 * 60
LANGUAGE_PROBE_LIMIT = 20


def concrete_source_language(provider, hoster_language="", source_language="", *, source_explicit=False):
    """Resolve audio evidence consistently for discovery and stream admission.

    A labeled hoster is authoritative, including unknown/subtitle-only labels.
    Catalog defaults are only usable for an unlabeled monolingual source.
    """
    if str(hoster_language or "").strip():
        return normalize_content_language(hoster_language)
    capabilities = {normalize_content_language(value) for value in provider_content_languages(provider)} - {""}
    stored = normalize_content_language(source_language)
    if source_explicit:
        return stored
    if len(capabilities) == 1:
        return stored or next(iter(capabilities))
    return ""


def needs_exact_episode_language(provider):
    return provider in {"huhu", "serienstream"} or len(provider_content_languages(provider)) > 1


def episode_language_state(languages, enabled):
    if languages is None:
        return "language_pending"
    return "available" if set(languages) & set(enabled) else "waiting_for_language"


def fresh_episode_languages(record, now):
    if not isinstance(record, dict):
        return None
    age = now - float(record.get("checked_at") or 0)
    if not 0 <= age < LANGUAGE_EVIDENCE_TTL:
        return None
    return [normalize_content_language(value) for value in record.get("languages", [])
            if normalize_content_language(value)]
