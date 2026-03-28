"""FEMA National Risk Index CSV parser — county-level hazard data."""

import logging
import os
from datetime import datetime, timezone

import pandas as pd

from ..db import upsert_city, upsert_climate_risk_data, get_climate_risk_data
from ..exceptions import FEMADataError

logger = logging.getLogger(__name__)

DEFAULT_NRI_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "fema", "NRI_Table_Counties.csv"
)

# Map from our internal hazard names to NRI CSV column names
HAZARD_COLUMNS = {
    "earthquake": "ERQK_RISKR",
    "tornado": "TRND_RISKR",
    "hurricane": "HRCN_RISKR",
    "wildfire": "WFIR_RISKR",
    "flood": "RFLD_RISKR",
    "heat_wave": "HWAV_RISKR",
    "cold_wave": "CWAV_RISKR",
}


def _match_county(city_name: str, state_abbr: str, counties: pd.DataFrame) -> pd.Series | None:
    """Find the best-matching county row for a city.

    Strategy: filter by state, then substring match city name against county name.
    Falls back to most populous county in the state if no match.
    """
    # Strip Census suffixes
    clean_name = city_name.lower()
    for suffix in (" city", " town", " village", " cdp", " borough", " municipality"):
        if clean_name.endswith(suffix):
            clean_name = clean_name[:-len(suffix)]
            break

    state_df = counties[counties["STATEABBRV"] == state_abbr]
    if state_df.empty:
        return None

    county_col = "COUNTY" if "COUNTY" in state_df.columns else "COUNTYNAME"

    # Try exact substring match
    for _, row in state_df.iterrows():
        county_name = str(row.get(county_col, "")).lower()
        if clean_name in county_name or county_name.replace(" county", "") in clean_name:
            return row

    # Try partial match (first word of city name)
    first_word = clean_name.split()[0] if clean_name else ""
    if first_word and len(first_word) > 3:
        for _, row in state_df.iterrows():
            county_name = str(row.get(county_col, "")).lower()
            if first_word in county_name:
                return row

    # Fallback: return first county in state (alphabetical)
    logger.warning("No county match for %s, %s — using first county in state", city_name, state_abbr)
    return state_df.iloc[0]


class FEMANRIClient:
    """Parser for FEMA National Risk Index county-level data."""

    def __init__(self, csv_path: str | None = None):
        self.csv_path = csv_path or DEFAULT_NRI_PATH
        self._df: pd.DataFrame | None = None

    @property
    def df(self) -> pd.DataFrame:
        """Lazy-load the NRI CSV."""
        if self._df is None:
            if not os.path.exists(self.csv_path):
                raise FEMADataError(f"FEMA NRI CSV not found at {self.csv_path}")
            logger.info("Loading FEMA NRI CSV from %s", self.csv_path)
            try:
                self._df = pd.read_csv(self.csv_path, dtype=str)
            except Exception as e:
                raise FEMADataError(f"Failed to read FEMA NRI CSV: {e}") from e
        return self._df

    def parse(self, city_name: str, state_abbr: str) -> dict:
        """Parse FEMA NRI data for the county matching a city.

        Returns:
            dict with keys: risk_rating, risk_score, and hazard_scores dict
        """
        logger.info("Parsing FEMA NRI data for %s, %s", city_name, state_abbr)

        row = _match_county(city_name, state_abbr, self.df)
        if row is None:
            logger.warning("No FEMA NRI data found for %s, %s", city_name, state_abbr)
            return {
                "risk_rating": None,
                "risk_score": None,
                "hazard_scores": {k: None for k in HAZARD_COLUMNS},
            }

        risk_rating = row.get("RISK_RATNG")
        try:
            risk_score = float(row.get("RISK_SCORE", 0))
        except (ValueError, TypeError):
            risk_score = None

        hazard_scores = {}
        for name, col in HAZARD_COLUMNS.items():
            hazard_scores[name] = row.get(col) if col in row.index else None

        return {
            "risk_rating": risk_rating,
            "risk_score": risk_score,
            "hazard_scores": hazard_scores,
        }

    def fetch_and_store(
        self,
        session,
        resolver_result: dict,
        max_age_days: int = 90,
    ) -> dict:
        """Parse FEMA NRI data and persist to database.

        Checks cache first; re-parses if data is stale.
        """
        city = upsert_city(session, resolver_result)

        # Check cache
        existing = get_climate_risk_data(session, city.id)
        if existing:
            age = (datetime.now(timezone.utc).replace(tzinfo=None) - existing.fetched_at).days
            if age <= max_age_days:
                logger.info("FEMA NRI data cached for city_id=%d (age: %dd)", city.id, age)
                return {
                    "risk_rating": existing.risk_rating,
                    "risk_score": existing.risk_score,
                    "hazard_scores": {
                        "earthquake": existing.earthquake_risk,
                        "tornado": existing.tornado_risk,
                        "hurricane": existing.hurricane_risk,
                        "wildfire": existing.wildfire_risk,
                        "flood": existing.flood_risk,
                        "heat_wave": existing.heat_wave_risk,
                        "cold_wave": existing.cold_wave_risk,
                    },
                }
            logger.info("FEMA NRI cache stale (%d days), re-parsing", age)

        # Parse CSV
        result = self.parse(resolver_result["city_name"], resolver_result["state_abbr"])

        # Store
        upsert_climate_risk_data(
            session=session,
            city_id=city.id,
            risk_rating=result["risk_rating"],
            risk_score=result["risk_score"],
            hazard_scores=result["hazard_scores"],
        )
        session.commit()
        logger.info("Stored FEMA NRI data for %s", resolver_result["city_name"])
        return result
