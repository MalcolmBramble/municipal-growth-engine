"""Tests for the Walk Score client."""

from unittest.mock import MagicMock, patch

import pytest

from src.ingest.walkscore import WalkScoreClient
from src.exceptions import WalkScoreError


MOCK_GEOCODER_RESPONSE = {
    "result": {
        "addressMatches": [
            {
                "coordinates": {"x": -82.9988, "y": 39.9612},
                "matchedAddress": "Columbus, OH",
            }
        ]
    }
}

MOCK_WALKSCORE_RESPONSE = {
    "status": 1,
    "walkscore": 41,
    "description": "Car-Dependent",
    "transit": {"score": 27, "description": "Minimal Transit"},
    "bike": {"score": 55, "description": "Bikeable"},
}


class TestGeocode:
    @patch("src.ingest.walkscore.requests.get")
    def test_geocode_returns_coords(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_GEOCODER_RESPONSE
        mock_get.return_value = mock_resp

        client = WalkScoreClient(api_key="test_key")
        lat, lon = client.geocode("Columbus city", "OH")

        assert lat == pytest.approx(39.9612)
        assert lon == pytest.approx(-82.9988)

    @patch("src.ingest.walkscore.requests.get")
    def test_geocode_no_results_raises(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"result": {"addressMatches": []}}
        mock_get.return_value = mock_resp

        client = WalkScoreClient(api_key="test_key")
        with pytest.raises(WalkScoreError, match="No geocoding results"):
            client.geocode("Faketown", "ZZ")

    @patch("src.ingest.walkscore.requests.get")
    def test_geocode_strips_city_suffix(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_GEOCODER_RESPONSE
        mock_get.return_value = mock_resp

        client = WalkScoreClient(api_key="test_key")
        client.geocode("Columbus city", "OH")

        # Verify the request used "Columbus" not "Columbus city"
        call_args = mock_get.call_args
        assert call_args[1]["params"]["city"] == "Columbus"


class TestFetchMocked:
    @patch("src.ingest.walkscore.requests.get")
    def test_fetch_returns_scores(self, mock_get):
        # First call: geocoder, second call: walkscore
        geo_resp = MagicMock()
        geo_resp.status_code = 200
        geo_resp.json.return_value = MOCK_GEOCODER_RESPONSE

        ws_resp = MagicMock()
        ws_resp.status_code = 200
        ws_resp.json.return_value = MOCK_WALKSCORE_RESPONSE

        mock_get.side_effect = [geo_resp, ws_resp]

        client = WalkScoreClient(api_key="test_key")
        result = client.fetch("Columbus city", "OH")

        assert result["walk_score"] == 41
        assert result["transit_score"] == 27
        assert result["bike_score"] == 55

    def test_fetch_no_api_key_raises(self):
        client = WalkScoreClient(api_key=None)
        # Clear env var too
        import os
        old = os.environ.pop("WALKSCORE_API_KEY", None)
        try:
            with pytest.raises(WalkScoreError, match="WALKSCORE_API_KEY not set"):
                client.fetch("Columbus", "OH")
        finally:
            if old:
                os.environ["WALKSCORE_API_KEY"] = old


class TestFetchAndStore:
    @patch("src.ingest.walkscore.requests.get")
    def test_stores_and_caches(self, mock_get, db_session):
        geo_resp = MagicMock()
        geo_resp.status_code = 200
        geo_resp.json.return_value = MOCK_GEOCODER_RESPONSE

        ws_resp = MagicMock()
        ws_resp.status_code = 200
        ws_resp.json.return_value = MOCK_WALKSCORE_RESPONSE

        mock_get.side_effect = [geo_resp, ws_resp]

        client = WalkScoreClient(api_key="test_key")
        resolver_result = {
            "city_name": "Columbus city", "state_abbr": "OH",
            "state_fips": "39", "place_fips": "18000",
        }

        result1 = client.fetch_and_store(db_session, resolver_result)
        assert result1["walk_score"] == 41

        # Second call uses cache
        mock_get.reset_mock()
        result2 = client.fetch_and_store(db_session, resolver_result)
        assert result2["walk_score"] == 41
        mock_get.assert_not_called()
