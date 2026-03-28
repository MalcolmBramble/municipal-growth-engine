"""Tests for the FIPS resolver."""

import pytest

from src.exceptions import ResolverError
from src.resolver import FIPSResolver


@pytest.fixture
def resolver():
    """Resolver using the project's CSV (must exist)."""
    return FIPSResolver()


class TestParseInput:
    def test_valid_abbreviation(self, resolver):
        city, state = resolver._parse_input("Columbus, OH")
        assert city == "Columbus"
        assert state == "OH"

    def test_valid_full_state_name(self, resolver):
        city, state = resolver._parse_input("Columbus, Ohio")
        assert city == "Columbus"
        assert state == "OH"

    def test_whitespace_handling(self, resolver):
        city, state = resolver._parse_input("  Columbus ,  OH  ")
        assert city == "Columbus"
        assert state == "OH"

    def test_no_comma_raises(self, resolver):
        with pytest.raises(ResolverError, match="Invalid format"):
            resolver._parse_input("Columbus OH")

    def test_unknown_state_raises(self, resolver):
        with pytest.raises(ResolverError, match="Unknown state"):
            resolver._parse_input("Columbus, ZZ")


class TestResolve:
    def test_columbus_oh(self, resolver):
        result = resolver.resolve("Columbus, OH")
        assert result["state_fips"] == "39"
        assert result["place_fips"] == "18000"
        assert result["state_abbr"] == "OH"
        assert "columbus" in result["city_name"].lower()

    def test_case_insensitive_city(self, resolver):
        result = resolver.resolve("columbus, OH")
        assert result["place_fips"] == "18000"

    def test_full_state_name(self, resolver):
        result = resolver.resolve("Columbus, Ohio")
        assert result["state_fips"] == "39"
        assert result["place_fips"] == "18000"

    def test_new_york(self, resolver):
        result = resolver.resolve("New York, NY")
        assert result["state_fips"] == "36"

    def test_unknown_city_raises(self, resolver):
        with pytest.raises(ResolverError, match="Could not resolve"):
            resolver.resolve("Faketown, OH")
