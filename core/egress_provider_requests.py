"""Requests facade for untrusted provider/probe URLs (no integration bypass)."""

from core import egress_requests as _requests


def __getattr__(name):
    return getattr(_requests, name)


class Session(_requests.Session):
    _egress_untrusted = True


def request(method, url, **kwargs):
    with Session() as session:
        return session.request(method, url, **kwargs)


def get(url, **kwargs):
    return request("get", url, **kwargs)


def post(url, **kwargs):
    return request("post", url, **kwargs)
