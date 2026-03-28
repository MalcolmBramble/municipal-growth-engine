"""Tests for FBI Crime Data API client."""

import pytest
from unittest.mock import patch, MagicMock

from src.ingest.fbi_crime import FBICrimeClient
from src.exceptions import FBICrimeError
from src.db import upsert_city


MOCK_STATE_ESTIMATES = [
    {
        "year": 2023,
        "population": 11800000,
        "violent_crime": 35400,
        "homicide": 700,
    },
    {
        "year": 2022,
        "population": 11700000,
        "violent_crime": 38610,
        "homicide": 780,
    },
    {
        "year": 2021,
        "population": 11600000,
        "violent_crime": 37120,
        "homicide": 810,
    },
]


class TestFBICrimeClient:
    """Unit tests for FBICrimeClient with mocked API."""

    def test_init_requires_key(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(FBICrimeError, match="FBI_API_KEY not set"):
                FBICrimeClient()

    def test_init_with_key(self):
        client = FBICrimeClient(api_key="test_key")
        assert client.api_key == "test_key"

    @patch("src.ingest.fbi_crime.requests.get")
    def test_fetch_state_estimates(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_STATE_ESTIMATES
        mock_get.return_value = mock_resp

        client = FBICrimeClient(api_key="test_key")
        results = client.fetch_state_estimates("OH")

        assert len(results) == 3
        # Sorted by year descending
        assert results[0]["year"] == 2023
        assert results[1]["year"] == 2022
        # Rate should be computed
        assert results[0]["violent_crime_rate"] == round(35400 / 11800000 * 100000, 2)

    @patch("src.ingest.fbi_crime.requests.get")
    def test_fetch_crime_data_with_trends(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_STATE_ESTIMATES
        mock_get.return_value = mock_resp

        client = FBICrimeClient(api_key="test_key")
        result = client.fetch_crime_data("OH")

        assert result["violent_crime_rate"] is not None
        assert result["homicide_count"] == 700
        assert result["current_year"] == 2023
        # Trend should be negative (crime decreased 2022→2023)
        assert result["violent_crime_trend"] < 0
        # Homicide trend should be negative (780→700)
        assert result["homicide_trend_pct"] < 0
        expected_pct = round((700 - 780) / 780 * 100, 2)
        assert result["homicide_trend_pct"] == expected_pct

    @patch("src.ingest.fbi_crime.requests.get")
    def test_fetch_crime_data_single_year(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [MOCK_STATE_ESTIMATES[0]]
        mock_get.return_value = mock_resp

        client = FBICrimeClient(api_key="test_key")
        result = client.fetch_crime_data("OH")

        assert result["violent_crime_rate"] is not None
        assert result["violent_crime_trend"] is None
        assert result["homicide_trend_pct"] is None

    @patch("src.ingest.fbi_crime.requests.get")
    def test_api_error_raises(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_get.return_value = mock_resp

        client = FBICrimeClient(api_key="test_key")
        with pytest.raises(FBICrimeError, match="FBI API error 500"):
            client.fetch_state_estimates("OH")

    @patch("src.ingest.fbi_crime.requests.get")
    def test_empty_response_raises(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        mock_get.return_value = mock_resp

        client = FBICrimeClient(api_key="test_key")
        with pytest.raises(FBICrimeError, match="No state estimate data"):
            client.fetch_state_estimates("XX")

    @patch("src.ingest.fbi_crime.requests.get")
    def test_fetch_and_store(self, mock_get, db_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_STATE_ESTIMATES
        mock_get.return_value = mock_resp

        resolver_result = {
            "city_name": "Columbus city",
            "state_abbr": "OH",
            "state_fips": "39",
            "place_fips": "18000",
        }

        client = FBICrimeClient(api_key="test_key")
        result = client.fetch_and_store(db_session, resolver_result)

        assert result["violent_crime_rate"] is not None
        assert result["homicide_count"] == 700

        # Verify data was stored
        from src.db import get_crime_data
        city = upsert_city(db_session, resolver_result)
        stored = get_crime_data(db_session, city.id)
        assert len(stored) == 3

    @patch("src.ingest.fbi_crime.requests.get")
    def test_fetch_and_store_uses_cache(self, mock_get, db_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_STATE_ESTIMATES
        mock_get.return_value = mock_resp

        resolver_result = {
            "city_name": "Columbus city",
            "state_abbr": "OH",
            "state_fips": "39",
            "place_fips": "18000",
        }

        client = FBICrimeClient(api_key="test_key")
        # First call — fetches from API
        result1 = client.fetch_and_store(db_session, resolver_result)
        assert mock_get.call_count == 2  # fetch_crime_data + fetch_state_estimates

        # Second call — uses cache
        mock_get.reset_mock()
        result2 = client.fetch_and_store(db_session, resolver_result)
        assert mock_get.call_count == 0
        assert result2["violent_crime_rate"] is not None
