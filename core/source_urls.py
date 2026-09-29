"""Non-network syntax validation for external source references."""
import ipaddress
from urllib.parse import urlsplit


def valid_source_link(value):
    # Syntax/structure only, no DNS lookup or media request. Actual resolution
    # remains protected by the existing public-network transport boundary.
    try:
        url = urlsplit(str(value))
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.port not in {None, 80, 443}:
            return False
        try:
            address = ipaddress.ip_address(url.hostname)
        except ValueError:
            return "." in url.hostname and not url.hostname.endswith((".local", ".localhost", ".internal", ".lan", ".home"))
        return address.is_global and not address.is_multicast and not address.is_reserved
    except ValueError:
        return False

