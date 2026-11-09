"""Jellyfin-negotiated playback with private, same-origin HLS resources."""

import re
from hashlib import sha256
from threading import RLock, Timer
from time import monotonic
from urllib.parse import urlencode, urljoin, urlsplit
from uuid import uuid4

from fastapi import HTTPException
from starlette.responses import Response, StreamingResponse

from core import egress_requests as requests
from integrations.jellyfin_auth import jellyfin_auth_headers
from integrations.jellyfin_client import forget_rd_playback, touch_rd_playback

DEVICE_ID = "RoyalDownloader"
URI = re.compile(r'URI="([^"]+)"')


def negotiate(base_url, key, item_id, profile_id, force_transcode=False):
    device_id = f"{DEVICE_ID}-{uuid4().hex}"
    profile = {
        "Name": "RoyalDownloader Web", "MaxStreamingBitrate": 20_000_000,
        "DirectPlayProfiles": [{"Container": "mp4,m4v", "Type": "Video",
                                "VideoCodec": "h264", "AudioCodec": "aac,mp3"}],
        "TranscodingProfiles": [{
            "Container": "ts", "Type": "Video", "AudioCodec": "aac", "VideoCodec": "h264",
            "Context": "Streaming", "Protocol": "hls", "MaxAudioChannels": "2",
            "MinSegments": 1, "BreakOnNonKeyFrames": True,
        }],
        "CodecProfiles": [{"Type": "Video", "Codec": "h264", "Conditions": [
            {"Condition": "LessThanEqual", "Property": "VideoBitDepth", "Value": "8", "IsRequired": True},
        ]}],
    }
    headers = jellyfin_auth_headers(key)
    headers["Authorization"] += f', Client="RoyalDownloader", Device="Web Player", DeviceId="{device_id}", Version="1"'
    try:
        with requests.post(f"{base_url}/Items/{item_id}/PlaybackInfo", headers=headers, json={
            "UserId": profile_id, "DeviceProfile": profile, "StartTimeTicks": 0,
            "MaxStreamingBitrate": profile["MaxStreamingBitrate"],
            "EnableDirectPlay": not force_transcode, "EnableDirectStream": False, "EnableTranscoding": True,
            "AllowVideoStreamCopy": not force_transcode, "AllowAudioStreamCopy": False,
            "AutoOpenLiveStream": False,
        }, timeout=(5, 20), allow_redirects=False) as response:
            if response.status_code != 200:
                raise HTTPException(502, "Jellyfin konnte die Wiedergabe nicht vorbereiten.")
            info = response.json()
    except (requests.RequestException, ValueError):
        raise HTTPException(502, "Jellyfin konnte die Wiedergabe nicht vorbereiten.") from None
    sources = [source for source in info.get("MediaSources") or [] if source.get("Protocol") == "File"]
    source = next((source for source in sources if source.get("SupportsDirectPlay") and not force_transcode), None)
    mode = "direct" if source else "hls"
    source = source or next((source for source in sources if source.get("TranscodingUrl")), None)
    if not source:
        raise HTTPException(502, "Jellyfin bietet keinen unterstützten Videostream an.")
    path = (f"{base_url}/Videos/{item_id}/stream.mp4?{urlencode({'Static': 'true', 'MediaSourceId': source['Id']})}"
            if mode == "direct" else source["TranscodingUrl"])
    return {
        "mode": mode, "path": path, "duration_ticks": source.get("RunTimeTicks") or 0,
        "play_session_id": info.get("PlaySessionId") or "", "headers": headers, "device_id": device_id,
    }


class PlaybackSessions:
    def __init__(self):
        self.lock = RLock()
        self.sessions = {}

    def open(self, base_url, key, item_id, profile_id, generation, owner, force_transcode=False):
        negotiated = negotiate(base_url, key, item_id, profile_id, force_transcode)
        token = uuid4().hex
        with self.lock:
            expired = [key for key, value in self.sessions.items() if monotonic() - value["used"] > 120]
        for expired_token in expired:
            self.close(expired_token)
        with self.lock:
            if len(self.sessions) >= 32:
                raise HTTPException(503, "Zu viele laufende Wiedergabesitzungen.")
            session = negotiated | {
                "base": base_url, "key": key, "owner": owner, "profile_id": profile_id,
                "generation": generation, "assets": {}, "used": monotonic(), "token": token,
            }
            url = self.asset(session, negotiated["path"], base_url + "/")
            self.sessions[token] = session
        self._schedule_expiry(session, 125)
        touch_rd_playback(token)
        return {"id": token, "url": url, "mode": session["mode"], "duration_ticks": session["duration_ticks"]}

    def _schedule_expiry(self, session, delay):
        timer = Timer(delay, self._expire, args=(session["token"],))
        timer.daemon = True
        session["expiry"] = timer
        timer.start()

    def _expire(self, token):
        with self.lock:
            session = self.sessions.get(token)
            if not session:
                return
            remaining = 120 - (monotonic() - session["used"])
            if remaining > 0:
                self._schedule_expiry(session, remaining + 1)
                return
            self.sessions.pop(token)
        forget_rd_playback(token)
        self.interrupt(session)

    def asset(self, session, path, parent):
        url = urljoin(parent, path)
        base, target = urlsplit(session["base"]), urlsplit(url)
        if (base.scheme, base.netloc) != (target.scheme, target.netloc) or target.username or target.fragment:
            raise HTTPException(502, "Jellyfin hat eine ungültige Stream-Adresse geliefert.")
        name = sha256(url.encode()).hexdigest()
        with self.lock:
            if len(session["assets"]) >= 20_000 and name not in session["assets"]:
                raise HTTPException(502, "Jellyfin-Wiedergabeliste ist zu groß.")
            session["assets"][name] = url
        return f"/api/media-center/playback/{session['token']}/asset/{name}"

    def get(self, token, owner, profile_id, generation):
        with self.lock:
            session = self.sessions.get(token)
            if not session or (session["owner"], session["profile_id"], session["generation"]) != (owner, profile_id, generation):
                raise HTTPException(404, "Die Wiedergabesitzung ist nicht mehr verfügbar.")
            session["used"] = monotonic()
        touch_rd_playback(token)
        return session

    def close(self, token):
        with self.lock:
            session = self.sessions.pop(token, None)
        forget_rd_playback(token)
        if session:
            session["expiry"].cancel()
            self.interrupt(session)

    def interrupt(self, session):
        if session["mode"] != "hls" or not session["play_session_id"]:
            return
        try:
            with requests.delete(f"{session['base']}/Videos/ActiveEncodings",
                                 params={"deviceId": session["device_id"], "playSessionId": session["play_session_id"]},
                                 headers=session["headers"], timeout=(3, 10), allow_redirects=False):
                pass
        except requests.RequestException:
            pass

    def response(self, session, name, range_header):
        with self.lock:
            url = session["assets"].get(name)
        if not url:
            raise HTTPException(404)
        headers = dict(session["headers"])
        headers["Accept-Encoding"] = "identity"
        if range_header:
            headers["Range"] = range_header
        try:
            upstream = requests.get(url, headers=headers, stream=True, timeout=(5, 45), allow_redirects=False)
        except requests.RequestException:
            raise HTTPException(502, "Das Videosegment ist nicht erreichbar.") from None
        if upstream.status_code not in (200, 206):
            status = 416 if upstream.status_code == 416 else 502
            upstream.close()
            raise HTTPException(status, "Jellyfin konnte das Videosegment nicht liefern.")
        mime = upstream.headers.get("Content-Type", "").split(";", 1)[0].lower()
        playlist = urlsplit(url).path.endswith(".m3u8") or mime in {
            "application/vnd.apple.mpegurl", "application/x-mpegurl",
        }
        if playlist:
            try:
                content = bytearray()
                for chunk in upstream.iter_content(65536):
                    content.extend(chunk)
                    if len(content) > 2 * 1024 * 1024:
                        raise HTTPException(502, "Jellyfin-Wiedergabeliste ist zu groß.")
                text = content.decode("utf-8-sig")
                if not text.startswith("#EXTM3U"):
                    raise HTTPException(502, "Jellyfin hat keine gültige Wiedergabeliste geliefert.")
                lines = []
                for line in text.splitlines():
                    if line and not line.startswith("#"):
                        line = self.asset(session, line.strip(), url)
                    elif 'URI="' in line:
                        line = URI.sub(lambda match: f'URI="{self.asset(session, match[1], url)}"', line)
                    lines.append(line)
                return Response("\n".join(lines) + "\n", media_type="application/vnd.apple.mpegurl",
                                headers={"Cache-Control": "no-store"})
            finally:
                upstream.close()

        def chunks():
            try:
                for chunk in upstream.iter_content(64 * 1024):
                    touch_rd_playback(session["token"])
                    yield chunk
            finally:
                upstream.close()

        response_headers = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
        for header in ("Content-Length", "Content-Range", "Accept-Ranges"):
            if header in upstream.headers:
                response_headers[header] = upstream.headers[header]
        return StreamingResponse(chunks(), status_code=upstream.status_code,
                                 media_type=mime or "application/octet-stream", headers=response_headers)
