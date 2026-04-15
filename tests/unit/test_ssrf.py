"""Tests for SSRF protection: URL scheme validation, private IP detection, DNS checks."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from proctx_crawler.core.ssrf import is_private_ip, resolve_and_check_ip, validate_url_scheme
from proctx_crawler.models import FetchError, InputValidationError

# ---------------------------------------------------------------------------
# validate_url_scheme
# ---------------------------------------------------------------------------


class TestValidateUrlScheme:
    def test_http_allowed(self) -> None:
        validate_url_scheme("http://example.com")

    def test_https_allowed(self) -> None:
        validate_url_scheme("https://example.com/path")

    def test_file_scheme_rejected(self) -> None:
        with pytest.raises(InputValidationError, match="Disallowed URL scheme"):
            validate_url_scheme("file:///etc/passwd")

    def test_ftp_scheme_rejected(self) -> None:
        with pytest.raises(InputValidationError, match="Disallowed URL scheme"):
            validate_url_scheme("ftp://example.com/file")

    def test_gopher_scheme_rejected(self) -> None:
        with pytest.raises(InputValidationError, match="Disallowed URL scheme"):
            validate_url_scheme("gopher://example.com")

    def test_data_scheme_rejected(self) -> None:
        with pytest.raises(InputValidationError, match="Disallowed URL scheme"):
            validate_url_scheme("data:text/html,<h1>hi</h1>")

    def test_javascript_scheme_rejected(self) -> None:
        with pytest.raises(InputValidationError, match="Disallowed URL scheme"):
            validate_url_scheme("javascript:alert(1)")


# ---------------------------------------------------------------------------
# is_private_ip
# ---------------------------------------------------------------------------


class TestIsPrivateIp:
    # IPv4 private ranges
    def test_loopback_127(self) -> None:
        assert is_private_ip("127.0.0.1") is True
        assert is_private_ip("127.255.255.255") is True

    def test_10_network(self) -> None:
        assert is_private_ip("10.0.0.1") is True
        assert is_private_ip("10.255.255.255") is True

    def test_172_16_network(self) -> None:
        assert is_private_ip("172.16.0.1") is True
        assert is_private_ip("172.31.255.255") is True

    def test_192_168_network(self) -> None:
        assert is_private_ip("192.168.0.1") is True
        assert is_private_ip("192.168.255.255") is True

    def test_link_local_169_254(self) -> None:
        assert is_private_ip("169.254.0.1") is True
        assert is_private_ip("169.254.255.255") is True

    def test_cgnat_100_64(self) -> None:
        assert is_private_ip("100.64.0.1") is True
        assert is_private_ip("100.127.255.255") is True

    # IPv6 private ranges
    def test_ipv6_loopback(self) -> None:
        assert is_private_ip("::1") is True

    def test_ipv6_unique_local(self) -> None:
        assert is_private_ip("fc00::1") is True
        assert is_private_ip("fd00::1") is True

    def test_ipv6_link_local(self) -> None:
        assert is_private_ip("fe80::1") is True

    # IPv4-mapped IPv6
    def test_ipv4_mapped_ipv6_private(self) -> None:
        assert is_private_ip("::ffff:127.0.0.1") is True
        assert is_private_ip("::ffff:10.0.0.1") is True
        assert is_private_ip("::ffff:192.168.1.1") is True

    def test_ipv4_mapped_ipv6_public(self) -> None:
        assert is_private_ip("::ffff:8.8.8.8") is False
        assert is_private_ip("::ffff:1.1.1.1") is False

    # Public IPs
    def test_public_ipv4(self) -> None:
        assert is_private_ip("8.8.8.8") is False
        assert is_private_ip("1.1.1.1") is False
        assert is_private_ip("93.184.216.34") is False

    def test_public_ipv6(self) -> None:
        assert is_private_ip("2001:4860:4860::8888") is False

    # Edge cases
    def test_invalid_ip_returns_false(self) -> None:
        assert is_private_ip("not-an-ip") is False

    def test_172_15_is_public(self) -> None:
        """172.15.x.x is NOT in the 172.16.0.0/12 private range."""
        assert is_private_ip("172.15.255.255") is False

    def test_172_32_is_public(self) -> None:
        """172.32.x.x is NOT in the 172.16.0.0/12 private range."""
        assert is_private_ip("172.32.0.1") is False

    def test_100_128_is_public(self) -> None:
        """100.128.x.x is NOT in the 100.64.0.0/10 CGNAT range."""
        assert is_private_ip("100.128.0.1") is False


# ---------------------------------------------------------------------------
# resolve_and_check_ip
# ---------------------------------------------------------------------------


def _make_addrinfo(ip: str, family: int = 2) -> list[tuple[int, int, int, str, tuple[str, int]]]:
    """Create a fake socket.getaddrinfo result."""
    return [(family, 1, 6, "", (ip, 0))]


class TestResolveAndCheckIp:
    def test_public_ip_returned(self) -> None:
        with patch("proctx_crawler.core.ssrf.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = _make_addrinfo("93.184.216.34")
            result = resolve_and_check_ip("example.com")
            assert result == "93.184.216.34"

    def test_private_ip_raises(self) -> None:
        with patch("proctx_crawler.core.ssrf.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = _make_addrinfo("127.0.0.1")
            with pytest.raises(FetchError, match="SSRF blocked"):
                resolve_and_check_ip("evil.example.com")

    def test_mixed_results_private_raises(self) -> None:
        """If any resolved IP is private, the check fails."""
        with patch("proctx_crawler.core.ssrf.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 6, "", ("93.184.216.34", 0)),
                (2, 1, 6, "", ("127.0.0.1", 0)),
            ]
            with pytest.raises(FetchError, match="SSRF blocked"):
                resolve_and_check_ip("mixed.example.com")

    def test_dns_failure_raises(self) -> None:
        import socket

        with patch("proctx_crawler.core.ssrf.socket.getaddrinfo") as mock_gai:
            mock_gai.side_effect = socket.gaierror("Name or service not known")
            with pytest.raises(FetchError, match="DNS resolution failed"):
                resolve_and_check_ip("nonexistent.example.com")

    def test_empty_results_raises(self) -> None:
        with patch("proctx_crawler.core.ssrf.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = []
            with pytest.raises(FetchError, match="no results"):
                resolve_and_check_ip("empty.example.com")

    def test_loopback_ipv6_raises(self) -> None:
        with patch("proctx_crawler.core.ssrf.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(10, 1, 6, "", ("::1", 0, 0, 0))]
            with pytest.raises(FetchError, match="SSRF blocked"):
                resolve_and_check_ip("ipv6-loopback.example.com")

    def test_recoverable_flag_on_private_ip(self) -> None:
        """SSRF block is not recoverable — the IP won't change."""
        with patch("proctx_crawler.core.ssrf.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = _make_addrinfo("10.0.0.1")
            with pytest.raises(FetchError) as exc_info:
                resolve_and_check_ip("internal.example.com")
            assert exc_info.value.recoverable is False

    def test_recoverable_flag_on_dns_failure(self) -> None:
        """DNS failure is recoverable — temporary network issues."""
        import socket

        with patch("proctx_crawler.core.ssrf.socket.getaddrinfo") as mock_gai:
            mock_gai.side_effect = socket.gaierror("Temporary failure in name resolution")
            with pytest.raises(FetchError) as exc_info:
                resolve_and_check_ip("flaky.example.com")
            assert exc_info.value.recoverable is True
