import unittest

import requests

from seerr_client import SeerrClient, SeerrRequest


class FakeResponse:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise self.error

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.post_calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class SeerrClientTests(unittest.TestCase):
    def test_base_url_is_normalized(self):
        for value in (
            " http://seerr:5055/ ",
            "http://seerr:5055/api/v1",
            "http://seerr:5055/API/V1/",
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    SeerrClient(value, "key").base_url, "http://seerr:5055"
                )

    def test_status_uses_api_key_and_timeout(self):
        session = FakeSession(FakeResponse({"version": "3.2.0"}))
        client = SeerrClient(
            "http://seerr:5055/", " secret ", timeout=4.5, session=session
        )

        self.assertEqual(client.status(), {"version": "3.2.0"})

        url, kwargs = session.calls[0]
        self.assertEqual(url, "http://seerr:5055/api/v1/status")
        self.assertEqual(kwargs["headers"]["X-Api-Key"], "secret")
        self.assertEqual(kwargs["timeout"], 4.5)

    def test_connection_failure_is_reported(self):
        session = FakeSession(requests.ConnectionError("offline"))
        client = SeerrClient("http://seerr:5055", "key", session=session)

        self.assertFalse(client.test_connection())
        self.assertIn("offline", client.last_error)

    def test_connection_checks_authenticated_request_endpoint(self):
        session = FakeSession(FakeResponse({"results": [], "pageInfo": {"results": 0}}))
        client = SeerrClient("http://seerr:5055", "key", session=session)

        self.assertTrue(client.test_connection())
        self.assertEqual(session.calls[0][0], "http://seerr:5055/api/v1/request")
        self.assertEqual(session.calls[0][1]["headers"]["X-Api-Key"], "key")

    def test_decline_request_updates_seerr_status(self):
        session = FakeSession(FakeResponse({"id": 44, "status": 3}))
        client = SeerrClient("http://seerr:5055", "key", session=session)

        self.assertTrue(client.decline_request(44))
        self.assertEqual(
            session.post_calls[0][0],
            "http://seerr:5055/api/v1/request/44/decline",
        )

    def test_approved_requests_are_paginated_and_parsed(self):
        session = FakeSession(
            FakeResponse(
                {
                    "pageInfo": {"results": 3},
                    "results": [
                        {
                            "id": 11,
                            "type": "movie",
                            "is4k": False,
                            "media": {"tmdbId": 101, "status": 5},
                            "seasons": [{"seasonNumber": 9}],
                        },
                        {
                            "id": "12",
                            "type": "tv",
                            "is4k": "true",
                            "media": {"tmdbId": "202", "status": 5, "status4k": 3},
                            "seasons": [
                                {"seasonNumber": 2},
                                {"seasonNumber": "1"},
                                {"seasonNumber": 2},
                            ],
                        },
                    ],
                }
            ),
            FakeResponse(
                {
                    "pageInfo": {"results": 3},
                    "results": [
                        {
                            "id": 13,
                            "type": "series",
                            "media": {"tmdbId": 303},
                            "seasons": [0, {"seasonNumber": 3}],
                        }
                    ],
                }
            ),
        )
        client = SeerrClient("http://seerr:5055", "key", session=session)

        result = client.approved_requests(page_size=2)

        self.assertEqual(
            result,
            [
                SeerrRequest(11, "movie", 101, media_status=5),
                SeerrRequest(12, "tv", 202, (1, 2), True, 3),
                SeerrRequest(13, "tv", 303, (0, 3), False),
            ],
        )
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(
            session.calls[0][1]["params"],
            {
                "take": 2,
                "skip": 0,
                "filter": "approved",
                "sort": "added",
                "sortDirection": "asc",
            },
        )
        self.assertEqual(session.calls[1][1]["params"]["skip"], 2)

    def test_invalid_requests_are_skipped_and_ids_are_deduplicated(self):
        valid = {"id": 7, "type": "movie", "media": {"tmdbId": 77}}
        session = FakeSession(
            FakeResponse(
                {
                    "pageInfo": {"results": 5},
                    "results": [
                        valid,
                        valid,
                        {"id": 8, "type": "book", "media": {"tmdbId": 88}},
                        {"id": 9, "type": "tv", "media": {}},
                        "invalid",
                    ],
                }
            )
        )

        result = SeerrClient("http://seerr", "key", session=session).approved_requests()

        self.assertEqual(result, [SeerrRequest(7, "movie", 77)])

    def test_invalid_list_response_is_an_api_failure(self):
        session = FakeSession(FakeResponse({"results": {}}))
        client = SeerrClient("http://seerr", "key", session=session)

        self.assertEqual(client.approved_requests(), [])
        self.assertIn("results", client.last_error)

    def test_unconfigured_client_does_not_make_requests(self):
        session = FakeSession()
        client = SeerrClient("http://seerr", "", session=session)

        self.assertFalse(client.configured)
        self.assertFalse(client.test_connection())
        self.assertEqual(client.approved_requests(), [])
        self.assertEqual(session.calls, [])


if __name__ == "__main__":
    unittest.main()
