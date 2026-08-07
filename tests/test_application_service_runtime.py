import importlib

import server


SERVICE_MODULES = (
    "auth",
    "updater",
    "media_clients",
    "movie_catalog",
    "movie_search_availability",
    "series_catalog",
    "persistence",
    "download_lifecycle",
    "source_resolution",
    "download_queue",
    "telegram_requests",
    "seerr",
    "telegram_commands",
    "automation",
    "movie_fallback_policy",
)


def test_every_service_export_remains_available_on_composition_root():
    for module_name in SERVICE_MODULES:
        module = importlib.import_module(f"application_services.{module_name}")
        for name in module._SERVICE_EXPORTS:
            assert hasattr(server, name), f"{module_name}.{name}"


def test_extracted_service_symbols_are_owned_by_service_modules():
    expected = {
        "auth_account": "auth",
        "automatic_update_loop": "updater",
        "get_jellyfin_client": "media_clients",
        "movie_catalog_page": "movie_catalog",
        "_tmdb_search_results": "movie_search_availability",
        "series_catalog_page": "series_catalog",
        "build_queue_payload": "persistence",
        "find_episode_fallbacks": "download_lifecycle",
        "find_movie_source_fallbacks": "movie_fallback_policy",
        "run_download_queue": "movie_fallback_policy",
        "_publish_telegram_movie_choices": "telegram_requests",
        "seerr_poll_once": "seerr",
        "handle_telegram_message": "telegram_commands",
        "watchlist_auto_check_loop": "automation",
    }
    for name, module in expected.items():
        assert getattr(server, name).__module__ == f"application_services.{module}"


def test_telegram_service_reads_the_live_bot_from_composition_root(monkeypatch):
    sent = []

    class Bot:
        def send(self, chat_id, text):
            sent.append((chat_id, text))

    monkeypatch.setattr(server, "_telegram_bot", Bot())

    server._telegram_send("42", "bereit")

    assert sent == [("42", "bereit")]
