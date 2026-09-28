"""Bounded non-download probes using the production hoster extractors."""
import json
import time
from urllib.parse import urljoin, urlsplit
from types import SimpleNamespace

from core.network_guard import request_proxy_kwargs, ensure_public_http_url
from core.source_urls import valid_source_link
from media import extractor
from media.hoster_contracts import runtime_contract, media_identity
from media.hoster_profiles import extract_profile, media_result, profile_url


class HosterProbeError(RuntimeError):
    def __init__(self, code):
        self.code = code


def classify_failure(message):
    text = str(message).lower()
    if any(word in text for word in ("captcha", "turnstile", "challenge", "login", "drm", "verification")):
        return "blocked"
    if "429" in text or "rate limit" in text:
        return "rate_limit"
    if "unsupported" in text or "new protocol" in text:
        return "needs_attention"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "404" in text or "not found" in text:
        return "removed"
    if any(word in text for word in ("network", "connection", "certificate", "resolve host")):
        return "network_error"
    return "parser_error"


class ProbeSession:
    """A single disposable session: 12 requests, 30 s, 2 MB total, safe redirects."""
    def __init__(self, seconds=30):
        import requests
        self.transport = requests.Session()
        self.transport.trust_env = False
        self.deadline = time.monotonic() + seconds
        self.requests, self.bytes = 0, 0
        self.responses, self.errors = [], []

    def request(self, method, url, **options):
        for _ in range(5):
            remaining = self.deadline - time.monotonic()
            self.requests += 1
            if remaining <= 0 or self.requests > 12:
                raise HosterProbeError("budget_exhausted")
            ensure_public_http_url(url)
            arguments = {key: value for key, value in options.items() if key in {"headers", "data", "json"}}
            arguments.update(request_proxy_kwargs(url))
            response = self.transport.request(method, url, **arguments, timeout=min(8, remaining), allow_redirects=False, stream=True, verify=True)
            try:
                status = response.status_code
                if status in {301, 302, 303, 307, 308}:
                    target = urljoin(url, response.headers.get("Location", ""))
                    if urlsplit(target).scheme != "https" or method != "GET" and urlsplit(target).netloc != urlsplit(url).netloc:
                        raise HosterProbeError("redirect_invalid")
                    url = target
                    if status == 303:
                        method, options = "GET", {}
                    continue
                if status == 429:
                    raise HosterProbeError("rate_limit")
                if status in {401, 403}:
                    raise HosterProbeError("blocked")
                if status == 404:
                    raise HosterProbeError("removed")
                if status >= 400:
                    raise HosterProbeError("network_error")
                # Never consume binary media; headers alone suffice for direct links.
                binary = response.headers.get("Content-Type", "").lower().startswith(("video/", "audio/", "application/octet-stream"))
                chunks = []
                if not binary:
                    for chunk in response.iter_content(16384):
                        self.bytes += len(chunk)
                        if self.bytes > 2_000_000 or time.monotonic() > self.deadline:
                            raise HosterProbeError("budget_exhausted")
                        chunks.append(chunk)
                text = b"".join(chunks).decode("utf-8", errors="replace")
                if any(marker in text.lower() for marker in ("cf-chl-", "cf-turnstile", "g-recaptcha", "captcha", "widevine", "drm_license", 'type="password"')):
                    raise HosterProbeError("blocked")
                result = SimpleNamespace(text=text, url=url, status_code=status, headers=response.headers, json=lambda: json.loads(text), raise_for_status=lambda: None)
                self.responses.append(result)
                return result
            finally:
                response.close()
        raise HosterProbeError("redirect_invalid")

    def _call(self, method, url, options):
        try:
            return self.request(method, url, **options)
        except Exception as exc:
            code = getattr(exc, "code", classify_failure(exc))
            self.errors.append(code)
            raise HosterProbeError(code) from None

    def get(self, url, **options):
        return self._call("GET", url, options)

    def post(self, url, **options):
        return self._call("POST", url, options)

    def close(self):
        self.transport.close()


class HosterProbe:
    def __init__(self, session_factory=ProbeSession):
        self.session_factory = session_factory

    def run(self, hoster, intensity="standard", profile=None, canaries=()):
        details, responses, steps = [], [], []
        deadline = time.monotonic() + (90 if intensity == "full" else 60)
        for canary in canaries[:5 if intensity == "full" else 3]:
            if time.monotonic() >= deadline:
                break
            started, session = time.monotonic(), self.session_factory()
            contract = runtime_contract(hoster, canary["url"], canary.get("provider", ""))
            if hasattr(session, "deadline"):
                session.deadline = min(session.deadline, deadline)
            code, result, resolver_started = "parser_error", None, None
            sample = canary["identity"]
            try:
                url = canary["url"]
                if profile:
                    url = profile_url(url, profile)
                response = session.get(url)
                reachability_ms = round((time.monotonic() - started) * 1000, 1)
                steps.append({"name": "reachability", "ok": True, "code": "ok", "sample": sample, "duration_ms": reachability_ms})
                if "embed" in contract.capabilities:
                    steps.append({"name": "embed", "ok": bool(response.text), "code": "ok" if response.text else "empty_extraction", "sample": sample, "duration_ms": None})
                if "redirect" in contract.capabilities:
                    steps.append({"name": "redirect", "ok": True, "code": "ok", "sample": sample, "duration_ms": None})
                if intensity != "light":
                    resolver_started = time.monotonic()
                if intensity == "light":
                    code = "recognition_only"
                elif profile and profile.get("player_selector"):
                    result = extract_profile(response.text, response.url, profile)
                elif contract.resolver == "direct":
                    result = media_result(url)
                elif contract.resolver == "yt_dlp":
                    # Existing simulator resolves metadata without downloading content.
                    from media.downloader import probe_stream_url
                    result = extractor.extract_stream_url(url, session=session, log_cb=lambda _message: None, pool=None)
                    if result is None and not session.errors:
                        ok, message = probe_stream_url(url, referer=url, timeout=max(1, min(15, int(deadline - time.monotonic()))))
                        result = (url, "web") if ok else None
                        code = "ok" if ok else classify_failure(message)
                else:
                    resolver = getattr(extractor, contract.resolver)
                    arguments = {"session": session, "log_cb": lambda _message: None}
                    if contract.resolver == "extract_stream_url":
                        arguments["pool"] = None
                    result = resolver(url, **arguments)
                if session.errors:
                    code, result = session.errors[0], None
                elif result:
                    if not valid_source_link(result[0]):
                        raise HosterProbeError("media_invalid")
                    ensure_public_http_url(result[0])
                    code = "ok"
                elif code == "parser_error" and contract.resolver == "extract_stream_url" and not profile:
                    code = "parser_error"
            except Exception as exc:
                code = getattr(exc, "code", classify_failure(exc))
            finally:
                duration = round((time.monotonic() - started) * 1000, 1)
                resolver_duration = round((time.monotonic() - resolver_started) * 1000, 1) if resolver_started is not None else None
                for response in session.responses:
                    # Raw pages/URLs remain ephemeral, never sent to diagnostics/store.
                    responses.append({"text": response.text, "url": response.url, "original_url": canary["url"], "identity": sample})
                session.close()
            ok = code == "ok"
            complete = ok or contract.probe_mode == "http_only"
            if not ok and code == "parser_error" and not complete:
                code = "browser_fallback_required" if contract.browser_fallback else "runtime_validation_required"
            for name in ("player", "resolver", "media_result"):
                if name in {"player", "resolver"} and name not in contract.capabilities:
                    continue
                steps.append({"name": name, "ok": None if intensity == "light" or not complete else ok, "code": code, "sample": sample, "duration_ms": resolver_duration if name == "resolver" else None})
            if result and result[1] in {"hls", "dash"} and "manifest" in contract.capabilities:
                steps.append({"name": "manifest", "ok": True, "code": "plausible_locator", "sample": sample, "duration_ms": None})
            details.append({"identity": sample, "ok": ok, "code": code, "duration_ms": duration, "probe_complete": complete, "probe_mode": contract.probe_mode, "provider": canary.get("provider", ""), "media_signature": media_identity(result[0]) if result and result[1] != "web" else ""})
        return {"details": details, "steps": steps, "responses": responses}
