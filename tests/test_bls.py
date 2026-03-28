"""Tests for the BLS unemployment client."""

from unittest.mock import MagicMock, patch

import pytest

from src.ingest.bls import BLSClient, state_unemployment_series


MOCK_BLS_RESPONSE = {
    "status": "REQUEST_SUCCEEDED",
    "responseTime": 100,
    "message": [],
    "Results": {
        "series": [
            {
                "seriesID": "LASST390000000003",
                "data": [
                    {"year": "2024", "period": "M06", "periodName": "June", "value": "4.1", "footnotes": [{}]},
                    {"year": "2024", "period": "M05", "periodName": "May", "value": "4.0", "footnotes": [{}]},
                    {"year": "2024", "period": "M04", "periodName": "April", "value": "4.2", "footnotes": [{}]},
                    {"year": "2024", "period": "M03", "periodName": "March", "value": "4.3", "footnotes": [{}]},
                    {"year": "2023", "period": "M06", "periodName": "June", "value": "3.8", "footnotes": [{}]},
                    {"year": "2023", "period": "M05", "periodName": "May", "value": "3.7", "footnotes": [{}]},
                    {"year": "2023", "period": "M04", "periodName": "April", "value": "3.9", "footnotes": [{}]},
                ]
            }
        ]
    }
}


class TestSeriesId:
    def test_state_series_id(self):
        assert state_unemployment_series("39") == "LASST390000000003"

    def test_state_series_id_padded(self):
        assert state_unemployment_series("06") == "LASST060000000003"


class TestFetchMocked:
    @patch("src.ingest.bls.requests.post")
    def test_fetch_parses_response(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_BLS_RESPONSE
        mock_post.return_value = mock_resp

        client = BLSClient(api_key="test_key")
        result = client.fetch(["LASST390000000003"])

        assert "LASST390000000003" in result
        points = result["LASST390000000003"]
        assert len(points) == 7
        # Should be sorted newest-first
        assert points[0]["year"] == 2024
        assert points[0]["period"] == "M06"
        assert points[0]["value"] == 4.1

    @patch("src.ingest.bls.requests.post")
    def test_fetch_unemployment_computes_trend(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_BLS_RESPONSE
        mock_post.return_value = mock_resp

        client = BLSClient(api_key="test_key")
        result = client.fetch_unemployment("39")

        assert result["unemployment_rate"] == 4.1
        assert result["unemployment_prior_year"] == 3.8
        assert result["unemployment_trend"] == 0.3  # 4.1 - 3.8
        assert result["series_id"] == "LASST390000000003"

    @patch("src.ingest.bls.requests.post")
    def test_fetch_and_store_caches(self, mock_post, db_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_BLS_RESPONSE
        mock_post.return_value = mock_resp

        client = BLSClient(api_key="test_key")
        resolver_result = {
            "city_name": "Columbus city", "state_abbr": "OH",
            "state_fips": "39", "place_fips": "18000",
        }

        # First call hits API
        result1 = client.fetch_and_store(db_session, resolver_result)
        assert result1["unemployment_rate"] == 4.1
        assert mock_post.call_count == 2  # fetch_unemployment + fetch for storage

        # Second call uses cache
        mock_post.reset_mock()
        result2 = client.fetch_and_store(db_session, resolver_result)
        assert result2["unemployment_rate"] == 4.1
        mock_post.assert_not_called()


class TestErrorHandling:
    @patch("src.ingest.bls.requests.post")
    def test_api_failure_raises(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_post.return_value = mock_resp

        client = BLSClient(api_key="test_key")
        from src.exceptions import BLSAPIError
        with pytest.raises(BLSAPIError, match="BLS API error 500"):
            client.fetch(["LASST390000000003"])

    @patch("src.ingest.bls.requests.post")
    def test_request_failed_status(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "REQUEST_NOT_SUCCEEDED",
            "message": ["Invalid series ID"],
        }
        mock_post.return_value = mock_resp

        client = BLSClient(api_key="test_key")
        from src.exceptions import BLSAPIError
        with pytest.raises(BLSAPIError, match="request failed"):
            client.fetch(["BADID"])
