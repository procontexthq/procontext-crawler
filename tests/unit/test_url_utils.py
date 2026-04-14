"""Tests for URL normalisation, pattern matching, and domain utilities."""

from __future__ import annotations

import re

from proctx_crawler.core.url_utils import (
    compile_pattern,
    is_same_domain,
    is_subdomain,
    matches_patterns,
    normalise_url,
    url_hash,
)

# ---------------------------------------------------------------------------
# normalise_url
# ---------------------------------------------------------------------------


class TestNormaliseUrl:
    def test_scheme_lowercased(self) -> None:
        assert normalise_url("HTTP://example.com") == "http://example.com/"
        assert normalise_url("HTTPS://example.com") == "https://example.com/"

    def test_host_lowercased(self) -> None:
        assert normalise_url("https://EXAMPLE.COM/path") == "https://example.com/path"
        assert normalise_url("https://Docs.Example.Com") == "https://docs.example.com/"

    def test_default_port_80_removed(self) -> None:
        assert normalise_url("http://example.com:80/path") == "http://example.com/path"

    def test_default_port_443_removed(self) -> None:
        assert normalise_url("https://example.com:443/page") == "https://example.com/page"

    def test_non_default_port_kept(self) -> None:
        assert normalise_url("http://example.com:8080/path") == "http://example.com:8080/path"
        assert normalise_url("https://example.com:8443/path") == "https://example.com:8443/path"

    def test_trailing_slash_removed(self) -> None:
        assert normalise_url("https://example.com/path/") == "https://example.com/path"

    def test_root_trailing_slash_kept(self) -> None:
        assert normalise_url("https://example.com/") == "https://example.com/"
        assert normalise_url("https://example.com") == "https://example.com/"

    def test_fragment_removed(self) -> None:
        assert normalise_url("https://example.com/page#section") == "https://example.com/page"

    def test_query_params_sorted(self) -> None:
        result = normalise_url("https://example.com/page?b=2&a=1")
        assert result == "https://example.com/page?a=1&b=2"

    def test_empty_query_removed(self) -> None:
        assert normalise_url("https://example.com/page?") == "https://example.com/page"

    def test_path_dot_segments_resolved(self) -> None:
        assert normalise_url("https://example.com/api/../guide/") == "https://example.com/guide"
        assert normalise_url("https://example.com/a/./b") == "https://example.com/a/b"

    def test_spec_example(self) -> None:
        result = normalise_url("HTTPS://Docs.Example.Com:443/api/../guide/?b=2&a=1#section")
        assert result == "https://docs.example.com/guide?a=1&b=2"

    def test_preserves_query_with_blank_values(self) -> None:
        result = normalise_url("https://example.com/page?key=&other=val")
        assert "key=" in result
        assert "other=val" in result

    def test_percent_encoding_unreserved_decoded(self) -> None:
        # %41 is 'A' (unreserved) — should be decoded
        assert normalise_url("https://example.com/%41") == "https://example.com/A"

    def test_percent_encoding_reserved_preserved(self) -> None:
        # %20 is space — should stay encoded
        result = normalise_url("https://example.com/hello%20world")
        assert "%20" in result

    def test_percent_encoding_dedup(self) -> None:
        # These should normalise to the same URL
        url1 = normalise_url("https://example.com/%7Euser")
        url2 = normalise_url("https://example.com/~user")
        assert url1 == url2

    def test_userinfo_stripped(self) -> None:
        # Userinfo should not appear in normalised URL
        result = normalise_url("https://example.com/path")
        assert "@" not in result


# ---------------------------------------------------------------------------
# compile_pattern
# ---------------------------------------------------------------------------


class TestCompilePattern:
    def test_single_star_matches_within_segment(self) -> None:
        pattern = compile_pattern("https://example.com/docs/*")
        assert pattern.search("https://example.com/docs/page1")
        assert not pattern.search("https://example.com/docs/sub/page1")

    def test_double_star_matches_across_segments(self) -> None:
        pattern = compile_pattern("https://example.com/docs/**")
        assert pattern.search("https://example.com/docs/page1")
        assert pattern.search("https://example.com/docs/sub/page1")
        assert pattern.search("https://example.com/docs/a/b/c")

    def test_exact_match(self) -> None:
        pattern = compile_pattern("https://example.com/page")
        assert pattern.search("https://example.com/page")
        assert not pattern.search("https://example.com/other")

    def test_no_match(self) -> None:
        pattern = compile_pattern("https://other.com/**")
        assert not pattern.search("https://example.com/page")

    def test_mixed_stars(self) -> None:
        pattern = compile_pattern("https://example.com/**/api/*")
        assert pattern.search("https://example.com/v1/api/users")
        assert pattern.search("https://example.com/a/b/api/items")
        assert not pattern.search("https://example.com/v1/api/nested/path")

    def test_returns_compiled_regex(self) -> None:
        result = compile_pattern("https://example.com/*")
        assert isinstance(result, re.Pattern)


# ---------------------------------------------------------------------------
# matches_patterns
# ---------------------------------------------------------------------------


class TestMatchesPatterns:
    def test_no_patterns_allows_all(self) -> None:
        assert matches_patterns("https://any.com/page") is True

    def test_empty_lists_allows_all(self) -> None:
        assert matches_patterns("https://any.com/page", include=[], exclude=[]) is True

    def test_exclude_only_blocks_matching(self) -> None:
        assert (
            matches_patterns(
                "https://example.com/api/v1",
                exclude=["**/api/**"],
            )
            is False
        )

    def test_exclude_only_allows_non_matching(self) -> None:
        assert (
            matches_patterns(
                "https://example.com/docs/intro",
                exclude=["**/api/**"],
            )
            is True
        )

    def test_include_only_allows_matching(self) -> None:
        assert (
            matches_patterns(
                "https://example.com/docs/intro",
                include=["**/docs/**"],
            )
            is True
        )

    def test_include_only_blocks_non_matching(self) -> None:
        assert (
            matches_patterns(
                "https://example.com/blog/post",
                include=["**/docs/**"],
            )
            is False
        )

    def test_exclude_wins_over_include(self) -> None:
        assert (
            matches_patterns(
                "https://example.com/docs/api/internal",
                include=["**/docs/**"],
                exclude=["**/api/**"],
            )
            is False
        )

    def test_include_and_exclude_matching_include_only(self) -> None:
        assert (
            matches_patterns(
                "https://example.com/docs/intro",
                include=["**/docs/**"],
                exclude=["**/api/**"],
            )
            is True
        )

    def test_none_patterns_allows_all(self) -> None:
        assert matches_patterns("https://any.com/page", include=None, exclude=None) is True


# ---------------------------------------------------------------------------
# is_same_domain
# ---------------------------------------------------------------------------


class TestIsSameDomain:
    def test_exact_match(self) -> None:
        assert is_same_domain("https://example.com/page", "https://example.com") is True

    def test_different_domain(self) -> None:
        assert is_same_domain("https://other.com/page", "https://example.com") is False

    def test_subdomain_is_not_same(self) -> None:
        assert is_same_domain("https://docs.example.com/page", "https://example.com") is False

    def test_case_insensitive(self) -> None:
        assert is_same_domain("https://EXAMPLE.COM/page", "https://example.com") is True

    def test_different_ports(self) -> None:
        # Ports are not part of hostname comparison
        assert is_same_domain("https://example.com:8080/page", "https://example.com") is True


# ---------------------------------------------------------------------------
# is_subdomain
# ---------------------------------------------------------------------------


class TestIsSubdomain:
    def test_direct_subdomain(self) -> None:
        assert is_subdomain("https://docs.example.com/page", "https://example.com") is True

    def test_nested_subdomain(self) -> None:
        assert is_subdomain("https://api.docs.example.com/page", "https://example.com") is True

    def test_same_domain_counts(self) -> None:
        assert is_subdomain("https://example.com/page", "https://example.com") is True

    def test_different_domain(self) -> None:
        assert is_subdomain("https://other.com/page", "https://example.com") is False

    def test_partial_match_not_subdomain(self) -> None:
        # "notexample.com" is NOT a subdomain of "example.com"
        assert is_subdomain("https://notexample.com/page", "https://example.com") is False

    def test_case_insensitive(self) -> None:
        assert is_subdomain("https://DOCS.EXAMPLE.COM/page", "https://example.com") is True


# ---------------------------------------------------------------------------
# url_hash
# ---------------------------------------------------------------------------


class TestUrlHash:
    def test_deterministic(self) -> None:
        assert url_hash("https://example.com") == url_hash("https://example.com")

    def test_16_chars(self) -> None:
        result = url_hash("https://example.com/some/path")
        assert len(result) == 16

    def test_hex_chars_only(self) -> None:
        result = url_hash("https://example.com")
        assert all(c in "0123456789abcdef" for c in result)

    def test_different_urls_different_hashes(self) -> None:
        h1 = url_hash("https://example.com/a")
        h2 = url_hash("https://example.com/b")
        assert h1 != h2
