"""Tests for the Census ACS client."""

import os
from unittest.mock import MagicMock, patch

import pytest

from src.ingest.census import CensusACSClient
from tests.conftest import MOCK_CENSUS_RESPONSE


class TestParseValue:
    def test_normal_number(self):
        assert CensusACSClient._parse_value("905748") == 905748.0

    def test_none_returns_none(self):
        assert CensusACSClient._parse_value(None) is None

    def test_sentinel_returns_none(self):
        assert CensusACSClient._parse_value("-666666666") is None

    def test_non_numeric_returns_none(self):
        assert CensusACSClient._parse_value("N/A") is None


class TestComputeDerived:
    def test_poverty_rate(self):
        raw = {"B17001_001E": 800000, "B17001_002E": 144000}
        derived = CensusACSClient.compute_derived(raw)
        assert derived["poverty_rate"] == 18.0

    def test_bachelors_plus(self):
        raw = {
            "B15003_001E": 600000,
            "B15003_022E": 150000,
            "B15003_023E": 60000,
            "B15003_024E": 12000,
            "B15003_025E": 18000,
        }
        derived = CensusACSClient.compute_derived(raw)
        assert derived["bachelors_plus_pct"] == 40.0

    def test_racial_composition(self):
        raw = {"B02001_001E": 1000, "B02001_002E": 500}
        derived = CensusACSClient.compute_derived(raw)
        assert derived["pct_white"] == 50.0

    def test_handles_zero_total(self):
        raw = {"B17001_001E": 0, "B17001_002E": 100}
        derived = CensusACSClient.compute_derived(raw)
        assert derived["poverty_rate"] is None

    def test_handles_missing_vars(self):
        derived = CensusACSClient.compute_derived({})
        assert derived["poverty_rate"] is None
        assert derived["bachelors_plus_pct"] is None


class TestFetchMocked:
    @patch("src.ingest.census.requests.get")
    def test_fetch_parses_response(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "data"
        mock_resp.json.return_value = MOCK_CENSUS_RESPONSE
        mock_get.return_value = mock_resp

        client = CensusACSClient(api_key="test_key")
        result = client.fetch("39", "18000")

        assert result["B01003_001E"] == 905748.0
        assert result["B19013_001E"] == 58326.0
        assert result["B17001_002E"] == 144000.0


class TestIntegration:
    """Integration tests that hit the real Census API."""

    def test_columbus_oh_end_to_end(self, db_session):
        """Full pipeline: resolve → fetch → store → verify."""
        from src.resolver import FIPSResolver

        # Resolve
        resolver = FIPSResolver()
        result = resolver.resolve("Columbus, OH")
        assert result["state_fips"] == "39"
        assert result["place_fips"] == "18000"

        # Fetch and store (Census API works without key for low volume)
        client = CensusACSClient(api_key=None)
        raw = client.fetch_and_store(db_session, result)

        # Population should be > 800K (Columbus is ~900K+)
        assert raw["B01003_001E"] is not None
        assert raw["B01003_001E"] > 800000

        # Median income should be reasonable
        assert raw["B19013_001E"] is not None
        assert raw["B19013_001E"] > 30000

        # Derived metrics
        derived = CensusACSClient.compute_derived(raw)
        assert derived["poverty_rate"] is not None
        assert 0 < derived["poverty_rate"] < 50
        assert derived["bachelors_plus_pct"] is not None
        assert derived["bachelors_plus_pct"] > 0
        assert derived["pct_white"] is not None
        assert derived["pct_black"] is not None
        assert derived["pct_hispanic"] is not None

        # Verify data persisted in DB
        from src.db import get_acs_data
        stored = get_acs_data(db_session, 1, 2023)
        assert len(stored) > 0
        stored_codes = {r.variable_code for r in stored}
        assert "B01003_001E" in stored_codes

        # Verify cache works (second call should not hit API)
        with patch("src.ingest.census.requests.get") as mock_get:
            raw2 = client.fetch_and_store(db_session, result)
            mock_get.assert_not_called()
        assert raw2["B01003_001E"] == raw["B01003_001E"]
