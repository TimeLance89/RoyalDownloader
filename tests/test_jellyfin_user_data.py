import json
import unittest
from unittest.mock import patch

from jellyfin_client import JellyfinClient


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class JellyfinUserDataTests(unittest.TestCase):
    def setUp(self):
        self.client = JellyfinClient("http://jellyfin", "key")

    @patch("urllib.request.urlopen")
    def test_lists_enabled_users(self, urlopen):
        urlopen.return_value = FakeResponse([
            {"Id": "u1", "Name": "Wohnzimmer", "Policy": {"IsDisabled": False}},
            {"Id": "u2", "Name": "Alt", "Policy": {"IsDisabled": True}},
        ])
        self.assertEqual(self.client.list_users(), [{"id": "u1", "name": "Wohnzimmer"}])

    @patch("urllib.request.urlopen")
    def test_reads_played_status_for_selected_user(self, urlopen):
        urlopen.return_value = FakeResponse({"Items": [
            {"SeriesName": "Dark", "ParentIndexNumber": 1, "IndexNumber": 1,
             "UserData": {"Played": True}},
            {"SeriesName": "Dark", "ParentIndexNumber": 1, "IndexNumber": 2,
             "UserData": {"Played": False}},
        ]})
        items = self.client.list_episodes_with_user_data("u1")
        self.assertEqual(self.client.watched_episodes_for_series("Dark", items), {(1, 1)})
        requested_url = urlopen.call_args.args[0].full_url
        self.assertIn("UserId=u1", requested_url)
        self.assertIn("EnableUserData=true", requested_url)

    def test_missing_user_has_no_trustworthy_status(self):
        self.assertIsNone(self.client.list_episodes_with_user_data(""))


if __name__ == "__main__":
    unittest.main()
