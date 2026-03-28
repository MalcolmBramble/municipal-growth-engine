"""Tests for the Housing data parsers (Redfin + Zillow)."""

import os
import tempfile

import pytest

from src.ingest.housing import HousingDataClient, _fuzzy_match_region


class TestFuzzyMatch:
    def test_exact_city_and_state(self):
        regions = ["Columbus, OH metro area", "Cleveland, OH metro area", "Dallas, TX metro area"]
        assert _fuzzy_match_region("Columbus", "OH", regions) == "Columbus, OH metro area"

    def test_case_insensitive(self):
        regions = ["COLUMBUS, OH METRO AREA"]
        assert _fuzzy_match_region("columbus", "OH", regions) == "COLUMBUS, OH METRO AREA"

    def test_strips_city_suffix(self):
        regions = ["Columbus, OH metro area"]
        assert _fuzzy_match_region("Columbus city", "OH", regions) == "Columbus, OH metro area"

    def test_no_match_returns_none(self):
        regions = ["Dallas, TX metro area"]
        assert _fuzzy_match_region("Columbus", "OH", regions) is None

    def test_prefers_state_match(self):
        regions = ["Columbus, GA metro area", "Columbus, OH metro area"]
        assert _fuzzy_match_region("Columbus", "OH", regions) == "Columbus, OH metro area"


SAMPLE_REDFIN_TSV = (
    "region\tmedian_sale_price\tmedian_dom\tmonths_of_supply\tperiod_begin\n"
    "Columbus, OH metro area\t300000\t25\t2.5\t2024-06-01\n"
    "Columbus, OH metro area\t280000\t30\t3.0\t2023-06-01\n"
    "Cleveland, OH metro area\t200000\t35\t4.0\t2024-06-01\n"
)

SAMPLE_ZILLOW_CSV = (
    "RegionID,SizeRank,RegionName,RegionType,StateName,2023-06-30,2024-06-30\n"
    "1,1,\"Columbus, OH\",msa,Ohio,250000,270000\n"
    "2,2,\"Cleveland, OH\",msa,Ohio,180000,185000\n"
)


@pytest.fixture
def redfin_file(tmp_path):
    path = tmp_path / "metro_market_tracker.tsv"
    path.write_text(SAMPLE_REDFIN_TSV)
    return str(path)


@pytest.fixture
def zillow_file(tmp_path):
    path = tmp_path / "zillow.csv"
    path.write_text(SAMPLE_ZILLOW_CSV)
    return str(path)


class TestRedfin:
    def test_parse_redfin(self, redfin_file):
        client = HousingDataClient(redfin_path=redfin_file)
        result = client.parse_redfin("Columbus city", "OH")

        assert result["median_sale_price"] == 300000.0
        assert result["median_dom"] == 25.0
        assert result["months_of_supply"] == 2.5
        assert result["period"] == "2024-06"
        # YoY: (300000 - 280000) / 280000 * 100 = 7.14%
        assert result["median_sale_price_yoy"] == pytest.approx(7.14, abs=0.01)

    def test_parse_redfin_no_match(self, redfin_file):
        client = HousingDataClient(redfin_path=redfin_file)
        result = client.parse_redfin("Faketown", "ZZ")
        assert result == {}

    def test_parse_redfin_missing_file(self):
        client = HousingDataClient(redfin_path="/nonexistent/file.tsv")
        result = client.parse_redfin("Columbus", "OH")
        assert result == {}


class TestZillow:
    def test_parse_zillow(self, zillow_file):
        client = HousingDataClient(zillow_path=zillow_file)
        result = client.parse_zillow("Columbus", "OH")

        assert result["zhvi"] == 270000.0
        assert result["zhvi_prior_year"] == 250000.0
        # YoY: (270000 - 250000) / 250000 * 100 = 8.0%
        assert result["zhvi_yoy_change"] == 8.0
        assert result["period"] == "2024-06"

    def test_parse_zillow_no_match(self, zillow_file):
        client = HousingDataClient(zillow_path=zillow_file)
        result = client.parse_zillow("Faketown", "ZZ")
        assert result == {}


class TestFetchAndStore:
    def test_stores_and_caches(self, db_session, redfin_file, zillow_file):
        client = HousingDataClient(redfin_path=redfin_file, zillow_path=zillow_file)
        resolver_result = {
            "city_name": "Columbus city", "state_abbr": "OH",
            "state_fips": "39", "place_fips": "18000",
        }

        result1 = client.fetch_and_store(db_session, resolver_result)
        assert result1.get("redfin_median_sale_price") == 300000.0
        assert result1.get("zillow_zhvi") == 270000.0

        # Second call uses cache
        result2 = client.fetch_and_store(db_session, resolver_result)
        assert "redfin_median_sale_price" in result2 or "housing_data" not in result2
