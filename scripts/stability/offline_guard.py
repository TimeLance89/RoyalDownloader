"""Offline tests: synthetic public DNS, no external sockets, guarded curl."""
import ipaddress
import os
import socket
import sys
from urllib.parse import urlsplit


def local(host):
    try:
        return host == 'localhost' or ipaddress.ip_address(host).is_loopback
    except (ValueError, TypeError):
        return False


def audit(event, args):
    if event == 'socket.connect':
        address = args[1]
        if isinstance(address, tuple) and not local(address[0]):
            raise OSError('OFFLINE TEST: external socket forbidden')
    elif event == 'socket.getaddrinfo' and args[0] not in (None, '') and not local(args[0]):
        raise OSError('OFFLINE TEST: real external DNS forbidden')

sys.addaudithook(audit)
_original_dns = socket.getaddrinfo


def fixture_dns(host, port, family=0, type=0, proto=0, flags=0):
    # DNS-based SSRF validation still runs against a public fixture address.
    # This does not authorize a connection; audit/native curl reject egress.
    if host in (None, '') or local(host):
        return _original_dns(host, port, family, type, proto, flags)
    try:
        address = str(ipaddress.ip_address(host))
    except ValueError:
        address = '93.184.216.34'
    af = socket.AF_INET6 if ':' in address else socket.AF_INET
    return [(af, type or socket.SOCK_STREAM, proto or socket.IPPROTO_TCP, '',
             (address, port, 0, 0) if af == socket.AF_INET6 else (address, port))]

socket.getaddrinfo = fixture_dns


def pytest_configure(config):
    global _configured
    if globals().get('_configured', False):
        return
    _configured = True
    for key in list(os.environ):
        if "proxy" in key.lower():
            os.environ.pop(key, None)
    from curl_cffi import Curl, CurlOpt
    real_setopt, real_perform, real_reset = Curl.setopt, Curl.perform, Curl.reset

    def setopt(self, option, value):
        if option in (CurlOpt.URL, CurlOpt.PROXY, CurlOpt.NOPROXY):
            values = getattr(self, '_offline_options', {})
            values[option] = value.decode() if isinstance(value, bytes) else value
            self._offline_options = values
        return real_setopt(self, option, value)

    def perform(self, *args, **kwargs):
        values = getattr(self, '_offline_options', {})
        if local(urlsplit(values.get(CurlOpt.URL, '')).hostname):
            return real_perform(self, *args, **kwargs)
        # Privacy regression tests use the in-process loopback egress guard.
        # Require explicit NO_PROXY disablement; inherited proxies are removed.
        if (local(urlsplit(values.get(CurlOpt.PROXY, '')).hostname)
                and values.get(CurlOpt.NOPROXY) == ''):
            return real_perform(self, *args, **kwargs)
        raise OSError('OFFLINE TEST: unmocked external native curl forbidden')

    def reset(self):
        self._offline_options = {}
        return real_reset(self)

    Curl.reset = reset
    Curl.setopt = setopt
    Curl.perform = perform
