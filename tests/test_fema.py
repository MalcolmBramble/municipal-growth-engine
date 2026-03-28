"""Tests for the FEMA NRI parser."""

import pytest

from src.ingest.fema_nri import FEMANRIClient, _match_county


SAMPLE_NRI_CSV = (
    "COUNTY,STATEABBRV,RISK_RATNG,RISK_SCORE,ERQK_RISKR,TRND_RISKR,HRCN_RISKR,WFIR_RISKR,RFLD_RISKR,HWAV_RISKR,CWAV_RISKR\n"
    "Franklin County,OH,Relatively Moderate,15.5,Very Low,Relatively Moderate,Very Low,Very Low,Relatively Low,Relatively Moderate,Relatively Low\n"
    "Cuyahoga County,OH,Relatively Moderate,14.2,Very Low,Relatively Low,Very Low,Very Low,Relatively Moderate,Relatively Low,Relatively Moderate\n"
    "Harris County,TX,Relatively High,22.1,Very Low,Relatively Low,Relatively High,Very Low,Relatively High,Relatively High,Very Low\n"
)


@pytest.fixture
def fema_csv(tmp_path):
    path = tmp_path / "NRI_Table_Counties.csv"
    path.write_text(SAMPLE_NRI_CSV)
    return str(path)


class TestMatchCounty:
    def test_matches_columbus_to_franklin(self, fema_csv):
        import pandas as pd
        df = pd.read_csv(fema_csv, dtype=str)
        row = _match_county("Columbus city", "OH", df)
        assert row is not None
        assert "Franklin" in row["COUNTY"]

    def test_no_state_match_returns_none(self, fema_csv):
        import pandas as pd
        df = pd.read_csv(fema_csv, dtype=str)
        row = _match_county("Portland", "OR", df)
        assert row is None


class TestParse:
    def test_parse_columbus(self, fema_csv):
        client = FEMANRIClient(csv_path=fema_csv)
        result = client.parse("Columbus city", "OH")

        assert result["risk_rating"] == "Relatively Moderate"
        assert result["risk_score"] == 15.5
        assert result["hazard_scores"]["earthquake"] == "Very Low"
        assert result["hazard_scores"]["tornado"] == "Relatively Moderate"
        assert result["hazard_scores"]["hurricane"] == "Very Low"
        assert result["hazard_scores"]["heat_wave"] == "Relatively Moderate"

    def test_parse_houston(self, fema_csv):
        client = FEMANRIClient(csv_path=fema_csv)
        result = client.parse("Houston city", "TX")

        assert result["risk_rating"] == "Relatively High"
        assert result["hazard_scores"]["hurricane"] == "Relatively High"
        assert result["hazard_scores"]["flood"] == "Relatively High"

    def test_missing_csv_raises(self):
        client = FEMANRIClient(csv_path="/nonexistent/file.csv")
        from src.exceptions import FEMADataError
        with pytest.raises(FEMADataError, match="not found"):
            client.parse("Columbus", "OH")


class TestFetchAndStore:
    def test_stores_and_caches(self, db_session, fema_csv):
        client = FEMANRIClient(csv_path=fema_csv)
        resolver_result = {
            "city_name": "Columbus city", "state_abbr": "OH",
            "state_fips": "39", "place_fips": "18000",
        }

        result1 = client.fetch_and_store(db_session, resolver_result)
        assert result1["risk_rating"] == "Relatively Moderate"

        # Second call uses cache
        result2 = client.fetch_and_store(db_session, resolver_result)
        assert result2["risk_rating"] == "Relatively Moderate"
