import ipaddress
import socket
from urllib.parse import urlparse


def is_internal_host(hostname: str) -> bool:
    """Return True if hostname resolves to any private/internal IP address."""
    if not hostname:
        return True
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return True  # unresolvable = block
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        ):
            return True
    return False


def validate_external_https(url: str) -> tuple[bool, str]:
    """Validate that url is HTTPS and resolves to a public host.

    Returns (True, '') on success, or (False, reason) on failure.
    """
    p = urlparse(url)
    if p.scheme != 'https':
        return False, 'must_be_https'
    if not p.hostname:
        return False, 'no_host'
    if is_internal_host(p.hostname):
        return False, 'internal_host'
    return True, ''
