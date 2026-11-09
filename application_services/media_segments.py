"""On-demand Jellyfin marker validation, bounded TTL cache and single flight.

Permission reads deliberately stay outside the result cache. No media is opened
or analyzed, and no scheduler, persistent data or background thread is created.
"""

from collections import OrderedDict
from concurrent.futures import Future, TimeoutError
from dataclasses import dataclass, field
from threading import Lock
from time import monotonic

from core import egress_requests as requests
from integrations.jellyfin_client import JellyfinClient
from integrations.jellyfin_saved import jellyfin_id

TICKS_PER_SECOND = 10_000_000
MAX_TICKS = 2**63 - 1
MAX_SEGMENTS = 256


@dataclass(frozen=True)
class Segment:
    type: str
    start_ticks: int
    end_ticks: int

    def payload(self):
        return {"type": self.type, "start_seconds": self.start_ticks / TICKS_PER_SECOND,
                "end_seconds": self.end_ticks / TICKS_PER_SECOND}


@dataclass(frozen=True)
class SegmentResult:
    status: str
    segments: tuple[Segment, ...] = ()
    discarded: int = 0
    http_status: int = 200
    code: str = ""
    message: str = ""

    def payload(self, item_id):
        result = {"media_id": item_id, "available": bool(self.segments), "status": self.status,
                  "segments": [segment.payload() for segment in self.segments]}
        if self.discarded:
            result["discarded_segments"] = self.discarded
        if self.code:
            result["error"] = {"code": self.code, "message": self.message}
        return result


class SegmentError(Exception):
    def __init__(self, http_status, code, message, status="error"):
        super().__init__(message)
        self.result = SegmentResult(status, http_status=http_status, code=code, message=message)


@dataclass(frozen=True)
class _Connection:
    base_url: str
    generation: int
    api_key: str = field(repr=False)


def _invalid_response():
    return SegmentError(502, "invalid_jellyfin_response", "Jellyfin lieferte ungültige Segmentdaten.")


def _ticks(value):
    return type(value) is int and 0 <= value <= MAX_TICKS


def normalize_segments(item_id, payload, duration_ticks=None):
    """Keep only unambiguous, item-bound Intro/Outro ranges; never clamp times."""
    item_id = jellyfin_id(item_id)
    if not isinstance(payload, dict) or not isinstance(payload.get("Items"), list):
        raise _invalid_response()
    rows = payload["Items"]
    total = payload.get("TotalRecordCount", len(rows))
    if type(total) is not int or total != len(rows) or len(rows) > MAX_SEGMENTS:
        raise _invalid_response()
    duration = duration_ticks if _ticks(duration_ticks) and duration_ticks > 0 else None
    candidates, discarded = set(), 0
    for row in rows:
        if not isinstance(row, dict):
            discarded += 1
            continue
        kind = row.get("Type")
        if not isinstance(kind, str):
            discarded += 1
            continue
        if kind not in ("Intro", "Outro"):
            continue
        start, end = row.get("StartTicks"), row.get("EndTicks")
        try:
            same_item = jellyfin_id(row.get("ItemId")) == item_id
        except (ValueError, TypeError, AttributeError):
            same_item = False
        if (not same_item or not _ticks(start) or not _ticks(end) or end <= start
                or (duration is not None and end > duration)):
            discarded += 1
            continue
        candidates.add(Segment(kind, start, end))
    ordered = sorted(candidates, key=lambda segment: (segment.start_ticks, segment.end_ticks, segment.type))
    conflicts = set()
    for index, left in enumerate(ordered):
        for right in ordered[index + 1:]:
            overlaps = right.start_ticks < left.end_ticks
            reversed_order = left.type == "Outro" and right.type == "Intro"
            if overlaps or reversed_order:
                conflicts.update((left, right))
    discarded += len(conflicts)
    segments = tuple(segment for segment in ordered if segment not in conflicts)
    if discarded and not segments:
        raise SegmentError(502, "invalid_media_segments", "Die Intro-/Abspannmarkierungen sind ungültig oder widersprüchlich.")
    return SegmentResult("partial" if discarded else "available" if segments else "empty", segments, discarded)


class SegmentCache:
    def __init__(self, *, clock=monotonic, capacity=1024, max_pending=16, wait_timeout=7):
        self.clock, self.capacity = clock, capacity
        self.max_pending, self.wait_timeout = max_pending, wait_timeout
        self._lock = Lock()
        self._entries = OrderedDict()
        self._pending = {}

    def get(self, key, load, *, refresh=False):
        with self._lock:
            pending = self._pending.get(key)
            if pending is None:
                cached = self._entries.get(key)
                if not refresh and cached and cached[0] > self.clock():
                    self._entries.move_to_end(key)
                    return cached[1]
                if len(self._pending) >= self.max_pending:
                    raise SegmentError(503, "segments_busy", "Segmentabruf ist ausgelastet. Bitte erneut versuchen.", "unavailable")
                self._entries.pop(key, None)
                pending = Future()
                self._pending[key] = pending
                leader = True
            else:
                leader = False
        if not leader:
            try:
                return pending.result(timeout=self.wait_timeout)
            except TimeoutError:
                raise SegmentError(503, "segments_busy", "Segmentabruf dauert zu lange. Bitte erneut versuchen.", "unavailable") from None
        try:
            try:
                result = load()
            except SegmentError as error:
                result = error.result
            ttl = (60 if result.status == "unsupported" else 5 if result.http_status != 200
                   else 30 if not result.segments else 300)
            with self._lock:
                self._entries[key] = (self.clock() + ttl, result)
                while len(self._entries) > self.capacity:
                    self._entries.popitem(last=False)
                pending.set_result(result)
                self._pending.pop(key, None)
            return result
        except BaseException as error:
            with self._lock:
                pending.set_exception(error)
                self._pending.pop(key, None)
            raise


def _read(call, *, stage):
    try:
        return call()
    except requests.HTTPError as error:
        status = getattr(error.response, "status_code", 0)
        if stage == "segments" and status in (404, 405, 501):
            raise SegmentError(503, "segments_endpoint_unavailable", "Die Jellyfin-Segmentschnittstelle ist nicht verfügbar.", "unsupported") from None
        if stage in ("user", "video") and status in (403, 404):
            raise SegmentError(403 if stage == "user" else 404, "profile_unavailable" if stage == "user" else "media_not_found",
                               "Profil oder Inhalt ist in Jellyfin nicht verfügbar.") from None
        if status in (401, 403):
            raise SegmentError(502, "jellyfin_auth_failed", "Jellyfin hat den Serverzugang abgewiesen.") from None
        if status == 429 or status >= 500:
            raise SegmentError(503, "jellyfin_unavailable", "Jellyfin ist vorübergehend nicht verfügbar.", "unavailable") from None
        raise _invalid_response() from None
    except requests.Timeout:
        raise SegmentError(503, "jellyfin_timeout", "Jellyfin antwortet nicht rechtzeitig.", "unavailable") from None
    except requests.RequestException:
        raise SegmentError(503, "jellyfin_unavailable", "Jellyfin ist vorübergehend nicht verfügbar.", "unavailable") from None
    except (ValueError, TypeError):
        raise _invalid_response() from None


class MediaSegments:
    def __init__(self, *, cache=None, client_factory=JellyfinClient):
        self.cache = cache if cache is not None else SegmentCache()
        self.client_factory = client_factory
        self._connection_lock = Lock()
        self._connection = None
        self._namespace = None

    def _connection_namespace(self, base_url, api_key, generation):
        """Opaque cache identity, not a credential verifier or stored key hash."""
        connection = _Connection(base_url, generation, api_key)
        with self._connection_lock:
            if connection != self._connection:
                self._connection = connection
                self._namespace = object()
            return self._namespace

    def read(self, base_url, api_key, generation, profile_id, item_id, *, refresh=False):
        profile_id, item_id = jellyfin_id(profile_id), jellyfin_id(item_id)
        namespace = self._connection_namespace(base_url, api_key, generation)
        client = self.client_factory(base_url, api_key, timeout=5)
        user = _read(lambda: client.media_segment_user(profile_id), stage="user")
        try:
            valid_user = isinstance(user, dict) and jellyfin_id(user.get("Id")) == profile_id
        except (ValueError, TypeError, AttributeError):
            valid_user = False
        if not valid_user or not isinstance(user.get("Policy"), dict):
            raise _invalid_response()
        if user["Policy"].get("IsDisabled", True) is not False or user["Policy"].get("EnableMediaPlayback", True) is not True:
            raise SegmentError(403, "profile_forbidden", "Das Jellyfin-Profil hat keinen Wiedergabezugriff.")
        videos = _read(lambda: client.media_segment_video(profile_id, item_id), stage="video")
        if not isinstance(videos, dict) or not isinstance(videos.get("Items"), list):
            raise _invalid_response()
        video = next(iter(videos["Items"]), None)
        if video is None:
            raise SegmentError(404, "media_not_found", "Dieser Inhalt ist im verknüpften Jellyfin-Profil nicht verfügbar.")
        try:
            matches = isinstance(video, dict) and jellyfin_id(video.get("Id")) == item_id
        except (ValueError, TypeError, AttributeError):
            matches = False
        if (not matches or len(videos["Items"]) != 1 or video.get("Type") not in ("Movie", "Episode")
                or video.get("LocationType") in ("Virtual", "Offline") or video.get("IsPlaceHolder") is True):
            raise SegmentError(404, "media_not_found", "Dieser Inhalt ist im verknüpften Jellyfin-Profil nicht verfügbar.")
        duration = video.get("RunTimeTicks")
        if duration is not None and (not _ticks(duration) or duration == 0):
            raise _invalid_response()
        key = (namespace, profile_id, item_id, duration)
        return self.cache.get(key, lambda: normalize_segments(item_id,
            _read(lambda: client.media_segments(item_id), stage="segments"), duration), refresh=refresh)
