"""urllib.request facade; proxy policy is evaluated again for redirects."""

import urllib.request as _request
from urllib.parse import urlsplit

from core.egress import EgressError, classify, get_manager


def __getattr__(name):
    return getattr(_request, name)


class _PolicyProxyHandler(_request.ProxyHandler):
    def __init__(self):
        super().__init__(
            {"http": "http://policy.invalid", "https": "http://policy.invalid"}
        )

    def proxy_open(self, req, proxy, type):
        external = (
            getattr(req, "_egress_external", False)
            or classify(req.full_url) == "external"
        )
        req._egress_external = external
        selected = get_manager().proxy_for(req.full_url, untrusted=external)
        # ProxyHandler.proxy_open honors process NO_PROXY, which could bypass
        # privacy policy. Only the policy above may choose a direct connection.
        if selected:
            req.set_proxy(urlsplit(selected).netloc, "http")


class _PolicyRedirectHandler(_request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            redirected._egress_external = getattr(req, "_egress_external", False)
        return redirected


def urlopen(
    url, data=None, timeout=_request.socket._GLOBAL_DEFAULT_TIMEOUT, *, context=None
):
    if get_manager().mode == "direct":
        return _request.urlopen(url, data=data, timeout=timeout, context=context)
    target = url.full_url if isinstance(url, _request.Request) else str(url)
    if urlsplit(target).scheme not in {"http", "https"}:
        raise EgressError("Privacy-Transport erlaubt nur HTTP(S)")
    handlers = [_PolicyProxyHandler(), _PolicyRedirectHandler()]
    if context is not None:
        handlers.append(_request.HTTPSHandler(context=context))
    return _request.build_opener(*handlers).open(url, data=data, timeout=timeout)
