"""Movie probe admission and routing state, separate from catalog presentation."""
import core.config as appconfig
from application_services.runtime import backend_value
from features.movie_probes import movie_probe_context, movie_source_probes
from providers.catalog import provider_supports_languages


def _movie_probe_context():
    return movie_probe_context(backend_value("state"))


def _movie_routing_incomplete():
    state = backend_value("state")
    ordered = backend_value("provider_order")("movies")
    with state.provider_priority_lock:
        configured = state.provider_enabled.get("movies", ordered)
        enabled = appconfig.normalize_provider_selection(configured, ordered)
        languages = set(state.content_languages)
    return any(provider_supports_languages(provider, languages)
               and not state.provider_health.routing_allowed(provider) for provider in enabled)


def _bounded_movie_details(jobs, budget, *, context=None, source_load=False):
    provider_for_value = backend_value("provider_for_value")
    return movie_source_probes.collect(
        [(key, provider_for_value(key) if source_load else key, job) for key, job in jobs],
        context=(_movie_probe_context(), context if context is not None else object()),
        timeout=budget,
    )
