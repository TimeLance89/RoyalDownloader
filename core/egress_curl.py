"""curl_cffi facade preserving impersonation, cookies and streaming behavior.

These transports consume provider URLs; LAN bypass is intentionally unavailable.
"""

from curl_cffi import CurlOpt
from curl_cffi import requests as _requests

from core.egress import EgressError, get_manager


def __getattr__(name):
    return getattr(_requests, name)


class Session(_requests.Session):
    def request(self, method, url, **kwargs):
        try:
            manager = get_manager()
            if manager.mode == "privacy":
                self.trust_env = False
                # An inherited NO_PROXY must not bypass even the local guard.
                self.curl_options[CurlOpt.NOPROXY] = ""
                self.curl_options[CurlOpt.PROXY] = manager.proxy_for(
                    url, untrusted=True
                )
                for option in (CurlOpt.CONNECT_TO, CurlOpt.RESOLVE, CurlOpt.DOH_URL):
                    self.curl_options.pop(option, None)
                kwargs.pop("proxy", None)
                kwargs.pop("proxy_auth", None)
                kwargs["doh_url"] = None
                kwargs.update(manager.request_options(url, untrusted=True))
            return super().request(method, url, **kwargs)
        except EgressError:
            raise _requests.RequestsError("Egress-Verbindung fehlgeschlagen") from None


def request(method, url, **kwargs):
    # Module-level curl_cffi options also include session constructor settings.
    session_keys = {"impersonate", "curl_options", "trust_env"}
    options = {key: kwargs.pop(key) for key in list(kwargs) if key in session_keys}
    with Session(**options) as session:
        return session.request(method, url, **kwargs)


def get(url, **kwargs):
    return request("GET", url, **kwargs)


def post(url, **kwargs):
    return request("POST", url, **kwargs)


def head(url, **kwargs):
    return request("HEAD", url, **kwargs)
