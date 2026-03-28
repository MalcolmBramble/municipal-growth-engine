"""Tests for the CityDataAggregator."""

from unittest.mock import MagicMock, patch

import pytest

from src.ingest.aggregator import CityDataAggregator, CityDataProfile


@pytest.fixture
def mock_aggregator(db_session):
    """Create an aggregator with all clients mocked."""
    resolver = MagicMock()
    resolver.resolve.return_value = {
        "city_name": "Columbus city",
        "state_abbr": "OH",
        "state_fips": "39",
        "place_fips": "18000",
    }

    census = MagicMock()
    census.fetch_and_store.return_value = {
        "B01003_001E": 905748.0,
        "B19013_001E": 58326.0,
        "B17001_001E": 800000.0,
        "B17001_002E": 144000.0,
        "B15003_001E": 600000.0,
        "B15003_022E": 150000.0,
        "B15003_023E": 60000.0,
        "B15003_024E": 12000.0,
        "B15003_025E": 18000.0,
        "B02001_001E": 905748.0,
        "B02001_002E": 480000.0,
        "B02001_003E": 270000.0,
        "B03003_001E": 905748.0,
        "B03003_003E": 63000.0,
    }

    bls = MagicMock()
    bls.fetch_and_store.return_value = {
        "unemployment_rate": 4.1,
        "unemployment_trend": 0.3,
    }

    housing = MagicMock()
    housing.fetch_and_store.return_value = {
        "redfin_median_sale_price": 300000.0,
        "redfin_median_sale_price_yoy": 7.14,
        "redfin_median_dom": 25.0,
        "redfin_months_of_supply": 2.5,
        "zillow_zhvi": 270000.0,
        "zillow_zhvi_yoy_change": 8.0,
    }

    walkscore = MagicMock()
    walkscore.fetch_and_store.return_value = {
        "walk_score": 41,
        "transit_score": 27,
        "bike_score": 55,
    }

    fema = MagicMock()
    fema.fetch_and_store.return_value = {
        "risk_rating": "Relatively Moderate",
        "risk_score": 15.5,
        "hazard_scores": {
            "earthquake": "Very Low",
            "tornado": "Relatively Moderate",
            "hurricane": "Very Low",
            "wildfire": "Very Low",
            "flood": "Relatively Low",
            "heat_wave": "Relatively Moderate",
            "cold_wave": "Relatively Low",
        },
    }

    # Patch the DB initialization in the aggregator constructor
    with patch("src.ingest.aggregator.get_engine"), \
         patch("src.ingest.aggregator.init_db"), \
         patch("src.ingest.aggregator.get_session", return_value=db_session):
        agg = CityDataAggregator(
            resolver=resolver,
            census_client=census,
            bls_client=bls,
            housing_client=housing,
            walkscore_client=walkscore,
            fema_client=fema,
        )
    return agg


class TestAggregate:
    def test_produces_complete_profile(self, mock_aggregator):
        profile = mock_aggregator.aggregate("Columbus, OH")

        # Identity
        assert profile.city_name == "Columbus city"
        assert profile.state_abbr == "OH"
        assert profile.state_fips == "39"
        assert profile.place_fips == "18000"

        # Census
        assert profile.population == 905748.0
        assert profile.median_income == 58326.0
        assert profile.poverty_rate == 18.0
        assert profile.bachelors_plus_pct == 40.0
        assert "pct_white" in profile.racial_composition

        # BLS
        assert profile.unemployment_rate == 4.1
        assert profile.unemployment_trend == 0.3

        # Housing
        assert profile.median_sale_price == 300000.0
        assert profile.price_yoy_change == 7.14
        assert profile.median_dom == 25.0
        assert profile.months_of_supply == 2.5
        assert profile.zhvi == 270000.0
        assert profile.zhvi_yoy_change == 8.0

        # Walk Score
        assert profile.walk_score == 41
        assert profile.transit_score == 27
        assert profile.bike_score == 55

        # FEMA
        assert profile.risk_rating == "Relatively Moderate"
        assert profile.risk_score == 15.5
        assert profile.hazard_scores["tornado"] == "Relatively Moderate"

    def test_handles_source_failure_gracefully(self, mock_aggregator):
        """If one source fails, others should still populate."""
        mock_aggregator.bls_client.fetch_and_store.side_effect = Exception("BLS down")
        mock_aggregator.walkscore_client.fetch_and_store.side_effect = Exception("WS down")

        profile = mock_aggregator.aggregate("Columbus, OH")

        # Census should still work
        assert profile.population == 905748.0
        # BLS should be None (failed)
        assert profile.unemployment_rate is None
        # Walk Score should be None (failed)
        assert profile.walk_score is None
        # Housing should still work
        assert profile.median_sale_price == 300000.0
        # FEMA should still work
        assert profile.risk_rating == "Relatively Moderate"


class TestCityDataProfile:
    def test_default_values(self):
        profile = CityDataProfile(
            city_name="Test", state_abbr="OH",
            state_fips="39", place_fips="00000",
        )
        assert profile.population is None
        assert profile.unemployment_rate is None
        assert profile.walk_score is None
        assert profile.racial_composition == {}
        assert profile.hazard_scores == {}
