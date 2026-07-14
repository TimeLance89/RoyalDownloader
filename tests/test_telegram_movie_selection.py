import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import server
from filmpalast_scraper import FilmpalastMovie, FilmpalastSearchResult, HosterInfo


def search_result(title, slug, year=""):
    return FilmpalastSearchResult(
        title=title,
        slug=slug,
        url=f"https://catalog.example/{slug}",
        year=year,
    )


def movie(title, slug, year="", cover="https://images.example/poster.jpg"):
    return FilmpalastMovie(
        title=title,
        url=f"https://stream.example/{slug}",
        year=year,
        cover_url=cover,
        hosters=[HosterInfo("VOE", f"https://voe.example/{slug}")],
    )


def option(title, slug, year=""):
    return {
        "result": search_result(title, slug, year),
        "movie": movie(title, slug, year),
        "fallback_movies": [],
        "title": title,
        "year": year,
        "cover_url": "https://images.example/poster.jpg",
    }


class FakeBot:
    def __init__(self):
        self.sent = []
        self.photos = []
        self.answers = []
        self.cleared = []
        self.next_message_id = 100

    def send(self, chat_id, text):
        self.sent.append((chat_id, text))
        self.next_message_id += 1
        return True

    def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))
        self.next_message_id += 1
        return self.next_message_id

    def send_photo(
        self, chat_id, photo, caption, reply_markup=None, content_type="image/jpeg",
    ):
        self.photos.append((chat_id, photo, caption, reply_markup, content_type))
        self.next_message_id += 1
        return self.next_message_id

    def answer_callback(self, callback_query_id, text=""):
        self.answers.append((callback_query_id, text))
        return True

    def clear_inline_keyboard(self, chat_id, message_id):
        self.cleared.append((chat_id, message_id))
        return True


class TelegramMovieSelectionTests(unittest.TestCase):
    def setUp(self):
        self.old_bot = server._telegram_bot
        self.old_cfg = server.state.telegram_cfg
        self.old_choices = server.state.telegram_series_choices
        server._telegram_bot = FakeBot()
        server.state.telegram_cfg = {
            "enabled": True, "bot_token": "token", "chat_id": "123",
        }
        server.state.telegram_series_choices = {}

    def tearDown(self):
        server._telegram_bot = self.old_bot
        server.state.telegram_cfg = self.old_cfg
        server.state.telegram_series_choices = self.old_choices

    def test_distinct_movies_require_selection_before_download(self):
        options = [option("Dune", "dune-1984", "1984"), option("Dune", "dune-2021", "2021")]
        with (
            patch("server.get_jellyfin_client", return_value=SimpleNamespace(configured=True)),
            patch("server.search_movie_candidates", return_value=[search_result("Dune", "dune")]),
            patch("server._build_telegram_movie_options", return_value=options),
            patch("server._publish_telegram_movie_choices") as publish,
            patch("server._run_telegram_movie_request") as run,
        ):
            server._handle_telegram_movie_request("123", "Dune")

        publish.assert_called_once_with("123", "Dune", options)
        run.assert_not_called()

    def test_duplicate_sources_are_grouped_but_different_years_remain(self):
        results = [
            search_result("Dune", "source-a", "2021"),
            search_result("Dune [Moflix]", "source-b", "2021"),
            search_result("Dune", "source-c", "1984"),
        ]
        loaded = [
            movie("Dune", "source-a", "2021"),
            movie("Dune [Moflix]", "source-b", "2021"),
            movie("Dune", "source-c", "1984"),
        ]

        with patch("server.load_movie_for_slug", side_effect=loaded):
            options = server._build_telegram_movie_options("Dune", results)

        self.assertEqual([(item["title"], item["year"]) for item in options], [
            ("Dune", "2021"),
            ("Dune", "1984"),
        ])
        self.assertEqual(len(options[0]["fallback_movies"]), 1)

    def test_choice_cards_use_posters_and_movie_callbacks(self):
        options = [option("Dune", "dune-1984", "1984"), option("Dune", "dune-2021", "2021")]

        with patch("server._fetch_cover_data", return_value=(b"poster", "image/jpeg")):
            server._publish_telegram_movie_choices("123", "Dune", options)

        self.assertEqual(len(server._telegram_bot.photos), 2)
        entry = next(iter(server.state.telegram_series_choices.values()))
        self.assertEqual(entry["kind"], "movie")
        callbacks = [
            photo[3]["inline_keyboard"][0][0]["callback_data"]
            for photo in server._telegram_bot.photos
        ]
        self.assertTrue(all(value.startswith("mr:") for value in callbacks))
        self.assertTrue(all(len(value.encode("utf-8")) <= 64 for value in callbacks))

    def test_movie_callback_consumes_choice_and_starts_selected_movie(self):
        selected = option("Dune", "dune-2021", "2021")
        server.state.telegram_series_choices["abcdefgh"] = {
            "kind": "movie",
            "chat_id": "123",
            "query": "Dune",
            "candidates": [selected],
            "created_at": time.monotonic(),
            "expires_at": time.monotonic() + 600,
            "message_ids": [51],
            "ready": True,
        }

        with patch("server._run_telegram_movie_request") as run:
            server.handle_telegram_callback("123", "cb-1", "mr:abcdefgh:0")

        run.assert_called_once_with(
            "123", "Dune", selected, wait_for_lock=True,
        )
        self.assertEqual(server.state.telegram_series_choices, {})
        self.assertEqual(server._telegram_bot.cleared, [("123", 51)])


if __name__ == "__main__":
    unittest.main()
