from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest

from application_services.media_segments import (
    MAX_SEGMENTS,
    MAX_TICKS,
    MediaSegments,
    Segment,
    SegmentCache,
    SegmentError,
    normalize_segments,
)
from core import egress_requests as requests
from integrations.jellyfin_client import JellyfinClient

ITEM = "1" * 32
PROFILE = "2" * 32


def row(kind="Intro", start=0, end=100, **fields):
    return {"ItemId": ITEM, "Type": kind, "StartTicks": start, "EndTicks": end, **fields}


def normalized(*rows, duration=1000):
    return normalize_segments(ITEM, {"Items": list(rows), "TotalRecordCount": len(rows)}, duration)


def test_ticks_are_exactly_normalized_and_duplicates_are_unambiguous():
    intro = row(start=1, end=920_000_001)
    outro = row("Outro", 24_500_000_000, 26_300_000_000)
    result = normalized(outro, intro, intro, duration=26_300_000_000)
    assert result.status == "available"
    assert result.payload(ITEM) == {
        "media_id": ITEM, "available": True, "status": "available", "segments": [
            {"type": "Intro", "start_seconds": 0.0000001, "end_seconds": 92.0000001},
            {"type": "Outro", "start_seconds": 2450.0, "end_seconds": 2630.0},
        ],
    }


@pytest.mark.parametrize("value", [-1, True, False, 1.5, float("nan"), float("inf"), "20", None, MAX_TICKS + 1])
@pytest.mark.parametrize("field", ["StartTicks", "EndTicks"])
def test_invalid_tick_values_are_not_coerced(value, field):
    with pytest.raises(SegmentError) as error:
        normalized(row(**{field: value}))
    assert error.value.result.http_status == 502


@pytest.mark.parametrize("segment", [row(start=50, end=50), row(start=51, end=50), row(end=1001),
                                       row(ItemId="3" * 32), row(ItemId=None), row(ItemId="not-an-id")])
def test_invalid_ranges_and_foreign_items_never_become_skip_targets(segment):
    with pytest.raises(SegmentError):
        normalized(segment)


def test_conflicting_ranges_are_all_discarded_without_choosing_an_arbitrary_winner():
    result = normalized(row(start=10, end=30), row(start=20, end=40), row("Outro", 800, 1000))
    assert result.status == "partial" and result.discarded == 2
    assert result.segments == (Segment("Outro", 800, 1000),)
    with pytest.raises(SegmentError):
        normalized(row("Outro", 10, 30), row(start=40, end=50))
    with pytest.raises(SegmentError):
        normalized(row(end=100), row("Outro", 90, 120))
    assert len(normalized(row(end=100), row("Outro", 100, 120)).segments) == 2


def test_no_markers_and_unrequested_segment_types_are_valid_empty_results():
    assert normalized().payload(ITEM) == {"media_id": ITEM, "available": False, "status": "empty", "segments": []}
    assert normalized(row("Recap"), row("Commercial"), row("Preview")).status == "empty"
    assert normalized(row(end=10_000), duration=None).segments[0].end_ticks == 10_000


@pytest.mark.parametrize("payload", [None, [], {}, {"Items": {}}, {"Items": [None]},
                                         {"Items": [], "TotalRecordCount": True},
                                         {"Items": [], "TotalRecordCount": 1},
                                         {"Items": [row()] * (MAX_SEGMENTS + 1)}])
def test_malformed_or_truncated_responses_are_not_reported_as_empty(payload):
    with pytest.raises(SegmentError):
        normalize_segments(ITEM, payload)


def test_segment_client_reuses_authentication_transport_and_rejects_non_uuid_paths(monkeypatch):
    calls = []

    def request(method, url, **options):
        calls.append((method, url, options))
        return SimpleNamespace(status_code=200, content=b"{}", raise_for_status=lambda: None, json=dict)

    monkeypatch.setattr("integrations.jellyfin_saved.requests.request", request)
    client = JellyfinClient("http://jellyfin/base", "private-key", timeout=5)
    client.media_segment_user(PROFILE)
    client.media_segment_video(PROFILE, ITEM)
    client.media_segments(ITEM)
    assert [call[1] for call in calls] == [f"http://jellyfin/base/Users/{PROFILE}", "http://jellyfin/base/Items",
                                          f"http://jellyfin/base/MediaSegments/{ITEM}"]
    for _, url, options in calls:
        assert "private-key" not in url
        assert options["headers"]["Authorization"] == 'MediaBrowser Token="private-key"'
        assert options["timeout"] == 5 and options["allow_redirects"] is False
    assert calls[1][2]["params"]["UserId"] == PROFILE
    assert calls[1][2]["params"]["Ids"] == ITEM
    assert calls[2][2]["params"] == {"includeSegmentTypes": "Intro,Outro"}
    with pytest.raises(ValueError):
        client.media_segments("../Users")
    assert len(calls) == 3


def test_cache_ttl_negative_ttl_failure_backoff_and_refresh():
    now, calls = [0], []
    cache = SegmentCache(clock=lambda: now[0])

    def load():
        calls.append(True)
        return normalized(row())

    first = cache.get("item", load)
    assert cache.get("item", load) is first and len(calls) == 1
    now[0] = 301
    cache.get("item", load)
    cache.get("item", load, refresh=True)
    assert len(calls) == 3
    cache.get("empty", lambda: normalized())
    now[0] += 29
    assert cache.get("empty", load).status == "empty"
    now[0] += 2
    assert cache.get("empty", load).status == "available"
    cache.get("failure", lambda: (_ for _ in ()).throw(SegmentError(503, "offline", "Unavailable", "unavailable")))
    now[0] += 4
    assert cache.get("failure", load).http_status == 503
    now[0] += 2
    assert cache.get("failure", load).http_status == 200


def test_refresh_failure_replaces_old_success_and_lru_storage_is_bounded():
    cache = SegmentCache(capacity=2)
    cache.get("a", lambda: normalized(row()))
    error = cache.get("a", lambda: (_ for _ in ()).throw(SegmentError(503, "offline", "Unavailable")), refresh=True)
    assert cache.get("a", lambda: pytest.fail("backoff should apply")) is error
    cache.get("b", normalized)
    cache.get("a", normalized)
    cache.get("c", normalized)
    assert list(cache._entries) == ["a", "c"]


def test_single_flight_does_not_hold_global_lock_during_io():
    cache, entered, release, calls = SegmentCache(), Event(), Event(), []

    def load():
        calls.append(True)
        entered.set()
        assert release.wait(2)
        return normalized(row())

    with ThreadPoolExecutor(max_workers=6) as pool:
        try:
            leader = pool.submit(cache.get, "same", load)
            assert entered.wait(1)
            followers = [pool.submit(cache.get, "same", load) for _ in range(4)]
            assert cache.get("different", normalized).status == "empty"
        finally:
            release.set()
        assert all(future.result() == leader.result() for future in followers)
    assert len(calls) == 1 and not cache._pending


def test_waiting_requests_timeout_without_cancelling_the_leader_and_capacity_is_bounded():
    cache, entered, release = SegmentCache(max_pending=1, wait_timeout=0.01), Event(), Event()

    def load():
        entered.set()
        assert release.wait(2)
        return normalized(row())

    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            leader = pool.submit(cache.get, "same", load)
            assert entered.wait(1)
            for key in ("same", "different"):
                with pytest.raises(SegmentError) as error:
                    cache.get(key, normalized)
                assert error.value.result.code == "segments_busy"
        finally:
            release.set()
        assert leader.result().status == "available"
    assert cache.get("same", normalized).status == "available"


def test_unexpected_loader_errors_release_the_single_flight_slot():
    cache = SegmentCache()
    with pytest.raises(RuntimeError):
        cache.get("item", lambda: (_ for _ in ()).throw(RuntimeError("programming error")))
    assert not cache._pending
    assert cache.get("item", normalized).status == "empty"


def test_inflight_refresh_is_shared_and_never_serves_the_previous_snapshot():
    cache, entered, release = SegmentCache(wait_timeout=0.01), Event(), Event()
    cache.get("item", lambda: normalized(row()))

    def load():
        entered.set()
        assert release.wait(2)
        return normalized()

    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            refreshing = pool.submit(cache.get, "item", load, refresh=True)
            assert entered.wait(1)
            with pytest.raises(SegmentError):
                cache.get("item", lambda: pytest.fail("must join refresh, not start another load"))
        finally:
            release.set()
        assert refreshing.result().status == "empty"
    assert cache.get("item", normalized).status == "empty"


@pytest.mark.parametrize("status,expected,code", [(404, 503, "segments_endpoint_unavailable"),
                                                 (405, 503, "segments_endpoint_unavailable"),
                                                 (501, 503, "segments_endpoint_unavailable"),
                                                 (401, 502, "jellyfin_auth_failed"),
                                                 (403, 502, "jellyfin_auth_failed"),
                                                 (429, 503, "jellyfin_unavailable"),
                                                 (500, 503, "jellyfin_unavailable"),
                                                 (400, 502, "invalid_jellyfin_response")])
def test_upstream_statuses_are_distinct_from_no_segments(status, expected, code):
    client = SimpleNamespace(
        media_segment_user=lambda _: {"Id": PROFILE, "Policy": {"IsDisabled": False}},
        media_segment_video=lambda *_: {"Items": [{"Id": ITEM, "Type": "Movie", "RunTimeTicks": 1000}]},
        media_segments=lambda _: (_ for _ in ()).throw(requests.HTTPError(response=SimpleNamespace(status_code=status))),
    )
    service = MediaSegments(client_factory=lambda *a, **kw: client)
    result = service.read("http://jf", "secret", 1, PROFILE, ITEM)
    assert (result.http_status, result.code, result.segments) == (expected, code, ())


@pytest.mark.parametrize("error,code", [(requests.Timeout("secret-url"), "jellyfin_timeout"),
                                       (requests.ConnectionError("secret-key"), "jellyfin_unavailable"),
                                       (ValueError("private-upstream-payload"), "invalid_jellyfin_response")])
def test_upstream_exceptions_do_not_leak_private_details(error, code):
    client = SimpleNamespace(media_segment_user=lambda _: (_ for _ in ()).throw(error))
    service = MediaSegments(client_factory=lambda *a, **kw: client)
    with pytest.raises(SegmentError) as failure:
        service.read("http://jf", "secret", 1, PROFILE, ITEM)
    assert failure.value.result.code == code
    assert str(error) not in str(failure.value.result.payload(ITEM))
