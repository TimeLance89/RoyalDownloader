"""Requests-compatible transport facade; enforces policy at every redirect hop."""

import requests as _requests

from core.egress import EgressError, get_manager


def __getattr__(name):
    return getattr(_requests, name)


class Session(_requests.Session):
    _egress_untrusted = False

    def send(self, request, **kwargs):
        try:
            manager = get_manager()
            if manager.mode == "privacy":
                # Respect existing guard routing (even for a private URL), so an
                # untrusted provider cannot become an integration LAN bypass.
                proxies = kwargs.get("proxies") or {}
                guarded = self._egress_untrusted or any(
                    str(value).startswith("http://127.0.0.1:")
                    for value in proxies.values()
                )
                kwargs.update(manager.request_options(request.url, untrusted=guarded))
            return super().send(request, **kwargs)
        except EgressError:
            raise _requests.ConnectionError(
                "Egress-Verbindung fehlgeschlagen"
            ) from None


def request(method, url, **kwargs):
    with Session() as session:
        return session.request(method, url, **kwargs)


def get(url, **kwargs):
    kwargs.setdefault("allow_redirects", True)
    return request("get", url, **kwargs)


def post(url, **kwargs):
    return request("post", url, **kwargs)


def head(url, **kwargs):
    kwargs.setdefault("allow_redirects", False)
    return request("head", url, **kwargs)


def put(url, **kwargs):
    return request("put", url, **kwargs)


def delete(url, **kwargs):
    return request("delete", url, **kwargs)


def patch(url, **kwargs):
    return request("patch", url, **kwargs)
