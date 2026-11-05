"""Shared inventory reads and generation-safe publication, no UI/network policy."""
import time
import logging

from integrations.jellyfin_reads import inventory_reads, is_background_read, movie_identities, scope_key

logger = logging.getLogger(__name__)

# dataset: cache prefix, fetch lock, generation counter, client loader
SPECS = {
    'movies': ('jellyfin_library', 'jellyfin_library_fetch_lock', 'jellyfin_movie_data_generation', 'list_movies'),
    'identities': ('jellyfin_movie_identities', 'jellyfin_movie_identities_fetch_lock', '', 'list_movie_identities'),
    'episodes': ('jellyfin_episodes', 'jellyfin_episodes_fetch_lock', 'jellyfin_episode_data_generation', 'list_episodes'),
    'series': ('jellyfin_series', 'jellyfin_series_fetch_lock', 'jellyfin_episode_data_generation', 'list_series'),
    'user_episodes': ('jellyfin_user_episodes', 'jellyfin_user_fetch_lock', 'jellyfin_episode_data_generation', 'list_episodes_with_user_data'),
}


def read_inventory(state, client, dataset, generation, *, user='', requested=None, background=None, on_start=None):
    def loader():
        try:
            method = getattr(client, SPECS[dataset][3])
            return method(user) if dataset == 'user_episodes' else method()
        except Exception:
            logger.warning('Jellyfin inventory unavailable kind=%s', dataset)
            return None
    return inventory_reads(state).read(scope_key(client, generation, dataset, user), loader,
        requested=requested, background=is_background_read() if background is None else background,
        on_start=on_start)


def _claim(state, dataset, generation, result):
    versions = getattr(state, '_jellyfin_inventory_publications', None)
    if versions is None:
        versions = state._jellyfin_inventory_publications = {}
    if generation != state.jellyfin_config_generation:
        return False
    old = versions.get(dataset)
    if old and old[0] == generation and old[1] >= result.serial:
        return False
    versions[dataset] = generation, result.serial
    return True


def _assign(state, prefix, value, now):
    setattr(state, prefix, value)
    setattr(state, prefix + '_time', now)
    setattr(state, prefix + '_available', True)
    setattr(state, prefix + '_retry_after', 0.0)


def publish_inventory(state, dataset, generation, result, *, identities=None):
    prefix, _lock, counter, _method = SPECS[dataset]
    if dataset == 'movies' and result.value is not None and identities is None:
        identities = movie_identities(result.value)
    with state.jellyfin_cache_lock:
        if not _claim(state, dataset, generation, result):
            return
        if counter:
            setattr(state, counter, getattr(state, counter, 0) + 1)
        now = time.time()
        if result.value is None:
            setattr(state, prefix + '_available', False)
            setattr(state, prefix + '_retry_after', now + 30)
            if dataset == 'movies' and _claim(state, 'identities', generation, result):
                state.jellyfin_movie_identities_available = False
                state.jellyfin_movie_identities_retry_after = now + 30
            return
        _assign(state, prefix, result.value, now)
        if dataset == 'movies' and _claim(state, 'identities', generation, result):
            _assign(state, 'jellyfin_movie_identities', identities, now)
        if dataset == 'episodes':
            targeted = getattr(state, 'jellyfin_targeted_episodes', None)
            if targeted is not None:
                targeted.clear()


def cached_inventory(state, get_client, dataset, *, force=False):
    reader = inventory_reads(state)
    requested = reader.clock()  # Capture BEFORE waiting for the legacy fetch lock.
    prefix, lock, counter, _method = SPECS[dataset]
    with getattr(state, lock):
        with state.jellyfin_cache_lock:
            client = get_client()
            generation = state.jellyfin_config_generation
            user = str(state.jellyfin_cfg.get('user_id') or '').strip() if dataset == 'user_episodes' else ''
            if not client.configured or (dataset == 'user_episodes' and not user):
                return None
            value = getattr(state, prefix)
            now = time.time()
            if not force and now < getattr(state, prefix + '_retry_after'):
                return value
            if not force and value is not None and getattr(state, prefix + '_available') and now - getattr(state, prefix + '_time') <= 300:
                return value
        def starting():
            if counter:
                with state.jellyfin_cache_lock:
                    if generation == state.jellyfin_config_generation:
                        setattr(state, counter, getattr(state, counter, 0) + 1)
        result = read_inventory(state, client, dataset, generation, user=user, requested=requested, on_start=starting)
        publish_inventory(state, dataset, generation, result)
        with state.jellyfin_cache_lock:
            return getattr(state, prefix)
