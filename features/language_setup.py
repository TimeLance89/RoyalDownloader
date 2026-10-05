"""Prepare a guided language change without mutating runtime or durable state."""
import hashlib
import json
from features.subscription_languages import subscription_content_languages
from providers.catalog import provider_supports_languages


def language_setup_revision(ui_language, languages, enabled, subscriptions, preferences):
    snapshot = [ui_language, sorted(languages), {kind: sorted(values) for kind, values in enabled.items()},
                sorted(str(entry.get("base_slug")) for entry in subscriptions), preferences]
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()


def language_setup_selection(languages, old_languages, orders, enabled):
    result = {}
    added = set(languages) - set(old_languages)
    for kind, providers in orders.items():
        matching = [p for p in providers if provider_supports_languages(p, languages)]
        chosen = [p for p in matching if p in enabled.get(kind, []) or provider_supports_languages(p, added)]
        if not chosen and kind != "anime":
            chosen = matching[:1]
        result[kind] = chosen
    if not result["movies"] or not result["series"]:
        raise ValueError("Die Inhaltssprachen benötigen passende Film- und Serienquellen.")
    return result


def language_setup_subscriptions(subscriptions, previous, old_languages, languages, selected):
    known = {entry["base_slug"] for entry in subscriptions}
    if not set(selected).issubset(known):
        raise ValueError("Die Serienliste hat sich geändert. Öffne das Sprach-Setup erneut.")
    return {entry["base_slug"]: list(languages) if entry["base_slug"] in selected
            else subscription_content_languages(entry, old_languages, previous)
            for entry in subscriptions}
