import os
import unittest
from unittest.mock import patch

import server


class ServerRecommenderTests(unittest.TestCase):
    def test_config_uses_settings_credentials_and_env_options(self):
        settings = {
            "url": "http://settings-jellyfin:8096/",
            "api_key": "settings-secret",
            "user_id": "settings-user",
        }
        env = {
            "JELLYFIN_URL": "http://wrong-jellyfin",
            "JELLYFIN_API_KEY": "wrong-secret",
            "JELLYFIN_USER_ID": "wrong-user",
            "COLLECTION_NAME": "Meine Empfehlungen",
            "TOP_N": "12",
        }
        with (
            patch.dict(os.environ, env, clear=True),
            patch("server.appconfig.load_jellyfin", return_value=settings),
        ):
            config = server._build_recommender_config()

        self.assertEqual(config.jellyfin_url, "http://settings-jellyfin:8096")
        self.assertEqual(config.api_key, "settings-secret")
        self.assertEqual(config.user_id, "settings-user")
        self.assertEqual(config.collection_name, "Meine Empfehlungen")
        self.assertEqual(config.top_n, 12)
        self.assertEqual(config.run_interval_seconds, 0)

    def test_missing_user_skips_without_api_call(self):
        settings = {
            "url": "http://jellyfin:8096",
            "api_key": "secret",
            "user_id": "",
        }
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("server.appconfig.load_jellyfin", return_value=settings),
            patch("server.run_jellyfin_recommender_once") as run,
        ):
            self.assertFalse(server._run_recommender_once())
        run.assert_not_called()

    def test_each_run_reloads_current_settings(self):
        first = {
            "url": "http://jellyfin-a:8096",
            "api_key": "secret-a",
            "user_id": "user-a",
        }
        second = {
            "url": "http://jellyfin-b:8096",
            "api_key": "secret-b",
            "user_id": "user-b",
        }
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("server.appconfig.load_jellyfin", side_effect=[first, second]),
            patch("server.run_jellyfin_recommender_once", return_value=[]) as run,
        ):
            self.assertTrue(server._run_recommender_once())
            self.assertTrue(server._run_recommender_once())

        self.assertEqual(run.call_args_list[0].args[0].user_id, "user-a")
        self.assertEqual(run.call_args_list[1].args[0].user_id, "user-b")

    def test_default_interval_is_one_day(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(server._recommender_interval_seconds(), 86400)

    def test_background_services_start_recommender_once(self):
        created = []

        class FakeThread:
            def __init__(self, *args, **kwargs):
                self.target = kwargs.get("target")
                self.started = False
                created.append(self)

            def start(self):
                self.started = True

        previous_started = server._background_services_started
        previous_thread = server._recommender_thread
        previous_seerr_thread = server._seerr_thread
        try:
            server._background_services_started = False
            with patch("server.threading.Thread", FakeThread):
                server.start_background_services()
                server.start_background_services()
        finally:
            server._background_services_started = previous_started
            server._recommender_thread = previous_thread
            server._seerr_thread = previous_seerr_thread
            server._recommender_stop_event.clear()
            server._recommender_wake_event.clear()
            server._seerr_stop_event.clear()
            server._seerr_wake_event.clear()

        targets = [thread.target for thread in created]
        self.assertEqual(targets.count(server.jellyfin_recommender_loop), 1)
        self.assertEqual(targets.count(server.seerr_poll_loop), 1)
        self.assertEqual(len(created), 5)
        self.assertTrue(all(thread.started for thread in created))


if __name__ == "__main__":
    unittest.main()
