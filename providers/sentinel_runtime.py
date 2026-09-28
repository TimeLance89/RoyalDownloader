"""Small adapter extension: declarative profiles and bounded HTTP-only probes.

Normal requests retain the adapter's transport. Probe sessions are disposable;
the ContextVar never changes a shared browser or a user's provider session.
"""
from __future__ import annotations

import time
import re
import socket
from functools import wraps
from contextlib import contextmanager
from contextlib import nullcontext
from contextvars import ContextVar
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

from providers.catalog import PROVIDER_CATALOG


class ProbeFailure(RuntimeError):
    def __init__(self, code, status=0):
        self.code, self.status = code, status
        super().__init__(code)


def confirmed_dns_failure(error):
    """Require target-boundary evidence, not a proxy/local DNS failure."""
    from core.network_guard import UnsafeNetworkTarget
    if not isinstance(error, UnsafeNetworkTarget):
        return False
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, socket.gaierror) and error.errno == socket.EAI_NONAME:
            return True
        error = error.__cause__ or error.__context__
    return False


@dataclass
class ProbeContext:
    provider: str
    profile: dict
    deadline: float
    maximum_requests: int = 32
    requests: int = 0
    responses: list = field(default_factory=list)
    failures: list = field(default_factory=list)


_context = ContextVar("provider_sentinel_probe", default=None)
_recovery = ContextVar("provider_runtime_recovery", default=None)
_runtime = None


def install_runtime(runtime):
    """Composition-root binding; adapters never import server/state."""
    global _runtime
    _runtime = runtime


def provider_routing_penalty(provider):
    """Diagnostics reorder usable routes; they never veto them."""
    try:
        diagnosis = _runtime.store.entry(provider, ("diagnosis",)).get("diagnosis") if _runtime else None
        return 1 if diagnosis in {"degraded", "needs_attention", "broken", "blocked", "repair_available"} else 0
    except Exception:
        return 0


def observe_hoster_safely(name, url, ok, duration_ms=0, provider="", message="", media_url=""):
    if _runtime is None or _context.get() is not None:
        return
    try:
        _runtime.hosters.observe(name, url, ok, duration_ms, provider, message, media_url)
    except Exception:
        # Technical monitoring must not alter production resolution outcomes.
        pass


def observe_language_safely(provider, media_type, language):
    """Optional bounded evidence; monitoring failure never changes a resolve."""
    if _runtime is None or _context.get() is not None:
        return
    try:
        _runtime.record_language_success(provider, media_type, language)
    except Exception:
        pass


def hoster_attempt_safely(name, url, provider=""):
    if _runtime is None or _context.get() is not None:
        return
    try:
        _runtime.hosters.begin(name, url, provider)
    except Exception:
        pass


def hoster_profile_safely(name, url):
    if _runtime is None:
        return {}
    try:
        from media.hoster_contracts import hoster_key
        return _runtime.hosters.repairs.profile(hoster_key(name, url))
    except Exception:
        return {}


@contextmanager
def runtime_recovery(provider):
    """Permit only the existing owner of an acquired ProviderHealth probe."""
    token = _recovery.set(provider)
    try:
        yield
    finally:
        _recovery.reset(token)


@contextmanager
def probe_context(provider, profile=None, *, seconds=60, maximum_requests=32):
    context = ProbeContext(provider, profile or {}, time.monotonic() + seconds, maximum_requests)
    token = _context.set(context)
    try:
        yield context
    finally:
        _context.reset(token)


def profile_for(provider):
    context = _context.get()
    if context and context.provider == provider:
        return context.profile
    return _runtime.profile(provider) if _runtime else {}


def safe_url(value):
    """No query, fragment, credentials or opaque redirect/token paths in history."""
    try:
        parsed = urlsplit(str(value))
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in {None, 443}:
            return ""
        return f"https://{parsed.hostname}/"
    except ValueError:
        return ""


def rewrite_url(provider, url):
    domain = profile_for(provider).get("domain")
    if not domain:
        return url
    parsed = urlsplit(url)
    if parsed.hostname in PROVIDER_CATALOG[provider].domains:
        return urlunsplit(("https", domain, parsed.path, parsed.query, parsed.fragment))
    return url


def apply_html_profile(provider, soup):
    """A constrained parsing view; the upstream page and application code stay intact."""
    profile = profile_for(provider)
    if provider != "filmpalast":
        return soup
    targets = {"catalog_selector": ("article", "liste"), "title_selector": ("h2", "bgDark"), "poster_selector": ("img", "cover2")}
    for field_name, (tag, class_name) in targets.items():
        selector = profile.get(field_name)
        if not selector:
            continue
        nodes = soup.select(selector)
        for node in nodes:
            node.name = tag
            node["class"] = list(dict.fromkeys([*(node.get("class") or []), class_name]))
            if field_name == "poster_selector" and not node.get("src"):
                node["src"] = node.get("data-src") or node.get("data-original") or ""
    return soup


def catalog_json(provider, data):
    path = profile_for(provider).get("catalog_json_path")
    if provider != "megakino" or not path or not isinstance(data, dict) or data.get("movies"):
        return data
    rows = data
    for key in path:
        rows = rows.get(key) if isinstance(rows, dict) else None
    return {**data, "movies": rows} if isinstance(rows, list) else data


def structural_signature(text):
    """Counts and field shapes only; page content is never persisted."""
    import json
    try:
        data = json.loads(text[:2_000_000])
        def shape(value, depth=0):
            if depth > 3:
                return type(value).__name__
            if isinstance(value, dict):
                return {str(key)[:60]: shape(item, depth + 1) for key, item in list(value.items())[:40]}
            if isinstance(value, list):
                return {"type": "list", "count": len(value), "item": shape(value[0], depth + 1) if value else None}
            return type(value).__name__
        return {"json": shape(data)}
    except ValueError:
        pass
    soup = BeautifulSoup(text[:2_000_000], "lxml")
    counts = {tag: len(soup.find_all(tag)) for tag in ("article", "a", "h1", "h2", "img", "iframe")}
    semantic = sorted({str(node.get("itemprop"))[:80] for node in soup.find_all(attrs={"itemprop": True})})[:30]
    return {"tags": counts, "semantic": semantic, "json_ld": len(soup.select('script[type="application/ld+json"]'))}


class AdapterSession:
    def __init__(self, provider, session):
        self.provider, self.session = provider, session

    def __getattr__(self, name):
        return getattr(self.session, name)

    def get(self, url, **kwargs):
        return self._request("get", url, kwargs)

    def post(self, url, **kwargs):
        return self._request("post", url, kwargs)

    def close(self):
        transport = getattr(self.session, "_curl", self.session)
        close = getattr(transport, "close", None)
        if close:
            close()

    def _request(self, method, url, kwargs):
        context = _context.get()
        probing = bool(context and context.provider == self.provider)
        if not probing and _recovery.get() != self.provider and _runtime and not _runtime.allowed(self.provider):
            raise ProbeFailure("provider_cooldown")
        url = rewrite_url(self.provider, url)
        started = time.monotonic()
        try:
            if probing:
                remaining = context.deadline - started
                context.requests += 1
                if remaining <= 0 or context.requests > context.maximum_requests:
                    raise ProbeFailure("budget_exhausted")
                # No browser recovery: call SessionManager's HTTP client directly.
                transport = getattr(self.session, "_curl", self.session)
                options = {k: v for k, v in kwargs.items() if k != "fast"}
                options["timeout"] = min(8, remaining)
                options["verify"] = True
                from core.network_guard import safe_proxy_url
                options["proxies"] = {"http": safe_proxy_url(), "https": safe_proxy_url()}
                response = getattr(transport, method)(url, **options)
                status = int(response.status_code)
                text = str(response.text or "")
                if len(text) > 2_000_000:
                    raise ProbeFailure("response_too_large", status)
                final_url = str(getattr(response, "url", url))
                context.responses.append({"origin": safe_url(url), "final_origin": safe_url(final_url),
                                          "status": status, "signature": structural_signature(text),
                                          "text": text[:250_000], "url": url})
                low = text[:30000].casefold()
                login_wall = "password" in low and bool(re.search(r"<title\b[^>]*>[^<]*(?:login|sign in|anmeld)[^<]*</title>", low))
                if status == 429:
                    raise ProbeFailure("rate_limit", status)
                if status in {401, 403} or login_wall or any(marker in low for marker in ("cf-chl-", "cf-turnstile", "g-recaptcha", "challenge-form", "checking your browser")):
                    raise ProbeFailure("verification_required", status)
                if status >= 500:
                    raise ProbeFailure("temporary_http", status)
                if status >= 400:
                    raise ProbeFailure("removed" if status == 404 else "http_error", status)
                # SessionManager returns HTML, regular clients return a Response.
                return text if hasattr(self.session, "_curl") else response
            domain = profile_for(self.provider).get("domain")
            if domain and urlsplit(url).hostname == domain and not hasattr(self.session, "_curl"):
                # Runtime repairs must retain the same DNS/redirect boundary as
                # validation. SessionManager already enforces its safe proxy.
                from core.network_guard import safe_proxy_url
                kwargs = {**kwargs, "verify": True, "proxies": {"http": safe_proxy_url(), "https": safe_proxy_url()}}
            result = getattr(self.session, method)(url, **kwargs)
            return result
        except Exception as error:
            if probing:
                context.failures.append((error.code, error.status) if isinstance(error, ProbeFailure) else ("domain_offline" if confirmed_dns_failure(error) else "network_error", 0))
            raise


def wrap_session(provider, session):
    return session if isinstance(session, AdapterSession) else AdapterSession(provider, session)


def monitor_adapter(provider):
    """Keep the real adapter contract; instrument its own parsing result."""
    def decorate(cls):
        original = cls.__init__

        @wraps(original)
        def initialize(self, *args, **kwargs):
            original(self, *args, **kwargs)
            self.session = wrap_session(provider, self.session)

        cls.__init__ = initialize
        for name in ("search", "search_series", "list_movies", "list_series", "browse", "get_movie", "get_series", "get_anime", "get_episode"):
            method = getattr(cls, name, None)
            if not method:
                continue

            def instrument(function, operation):
                @wraps(function)
                def call(self, *args, **kwargs):
                    context = _context.get()
                    probing = context and context.provider == provider
                    started = time.monotonic()
                    identity = str(args[0]) if args and operation.startswith("get_") else ""
                    recovery = False
                    if _runtime and hasattr(_runtime, "health") and not probing and _recovery.get() != provider and not _runtime.allowed(provider):
                        recovery = _runtime.health.begin_probe(provider)
                        if not recovery:
                            raise ProbeFailure("provider_cooldown")
                    try:
                        with runtime_recovery(provider) if recovery else nullcontext():
                            result = function(self, *args, **kwargs)
                    except Exception as error:
                        if recovery:
                            _runtime.health.finish_probe_error(provider, "runtime_recovery_failed")
                        if _runtime and not probing and not (isinstance(error, ProbeFailure) and error.code == "provider_cooldown"):
                            status = int(getattr(error, "status", 0) or getattr(getattr(error, "response", None), "status_code", 0) or 0)
                            observe_safely(provider, False, time.monotonic() - started, identity, None, operation,
                                           runtime_failure=status not in {404, 410})
                        raise
                    if _runtime and not probing:
                        usable = bool(result.get("results")) if isinstance(result, dict) and "results" in result else bool(result)
                        if usable or operation.startswith("get_"):
                            observe_safely(provider, usable, time.monotonic() - started, identity, result, operation)
                        if recovery and not usable:
                            _runtime.health.finish_probe_error(provider, "runtime_recovery_empty")
                    return result
                return call
            setattr(cls, name, instrument(method, name))
        return cls
    return decorate


def observe_safely(*args, **kwargs):
    # Diagnostics must never replace an adapter result/error with a disk or
    # notification failure. No exception text (possibly credentials) is logged.
    try:
        _runtime.observe(*args, **kwargs)
    except Exception:
        import logging
        logging.getLogger(__name__).warning("Provider Sentinel runtime observation unavailable")
