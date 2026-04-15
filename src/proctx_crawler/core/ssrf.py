"""SSRF protection: URL scheme validation, private IP detection, and DNS resolution checks."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import structlog

from proctx_crawler.models import ErrorCode, FetchError, InputValidationError

log = structlog.get_logger()

_ALLOWED_SCHEMES = frozenset({"http", "https"})

_PRIVATE_NETWORKS_V4 = [
    ipaddress.IPv4Network("127.0.0.0/8"),
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
    ipaddress.IPv4Network("169.254.0.0/16"),
    ipaddress.IPv4Network("100.64.0.0/10"),
]

_PRIVATE_NETWORKS_V6 = [
    ipaddress.IPv6Network("::1/128"),
    ipaddress.IPv6Network("fc00::/7"),
    ipaddress.IPv6Network("fe80::/10"),
]


def validate_url_scheme(url: str) -> None:
    """Validate that the URL uses an allowed scheme (http or https).

    Raises InputValidationError for disallowed schemes such as file://, ftp://, gopher://, data:,
    javascript:, etc.
    """
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise InputValidationError(
            code=ErrorCode.INVALID_INPUT,
            message=f"Disallowed URL scheme: {scheme!r}. Only http and https are allowed.",
        )


def is_private_ip(ip: str) -> bool:
    """Check whether an IP address belongs to a private or reserved range.

    Handles IPv4, IPv6, and IPv4-mapped IPv6 addresses (e.g. ::ffff:127.0.0.1).
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False

    # Handle IPv4-mapped IPv6 addresses: extract the embedded IPv4 address.
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped

    if isinstance(addr, ipaddress.IPv4Address):
        return any(addr in network for network in _PRIVATE_NETWORKS_V4)

    # IPv6 address
    return any(addr in network for network in _PRIVATE_NETWORKS_V6)


def resolve_and_check_ip(hostname: str) -> str:
    """Resolve a hostname and verify that none of the resolved IPs are private.

    Returns the first resolved public IP address.

    Raises FetchError if any resolved IP is private or if DNS resolution fails.
    """
    try:
        results = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchError(
            code=ErrorCode.FETCH_FAILED,
            message=f"DNS resolution failed for {hostname!r}: {exc}",
            recoverable=True,
        ) from exc

    if not results:
        raise FetchError(
            code=ErrorCode.FETCH_FAILED,
            message=f"DNS resolution returned no results for {hostname!r}",
            recoverable=True,
        )

    first_public_ip: str | None = None
    for _family, _type, _proto, _canonname, sockaddr in results:
        ip = str(sockaddr[0])
        if is_private_ip(ip):
            log.warning("ssrf_private_ip_blocked", hostname=hostname, ip=ip)
            raise FetchError(
                code=ErrorCode.FETCH_FAILED,
                message=f"SSRF blocked: {hostname!r} resolves to private IP {ip}",
                recoverable=False,
            )
        if first_public_ip is None:
            first_public_ip = ip

    # This should not happen given the non-empty results check above, but satisfy the type checker.
    if first_public_ip is None:  # pragma: no cover
        raise FetchError(
            code=ErrorCode.FETCH_FAILED,
            message=f"DNS resolution returned no usable results for {hostname!r}",
            recoverable=True,
        )

    return first_public_ip
