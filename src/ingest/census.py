"""Census ACS API client — fetches demographic, economic, and social data."""

import logging
import os
import time

import requests

from ..db import get_acs_data, upsert_acs_data, upsert_city
from ..exceptions import CensusAPIError

logger = logging.getLogger(__name__)

# ACS variable codes organized by dimension
VARIABLE_GROUPS = {
    "population": ["B01003_001E"],
    "income": ["B19013_001E"],
    "poverty": ["B17001_001E", "B17001_002E"],
    "education": [
        "B15003_001E",  # Total 25+
        "B15003_022E",  # Bachelor's
        "B15003_023E",  # Master's
        "B15003_024E",  # Professional
        "B15003_025E",  # Doctorate
    ],
    "race": [
        "B02001_001E",  # Total
        "B02001_002E",  # White alone
        "B02001_003E",  # Black/African American alone
        "B02001_004E",  # American Indian/Alaska Native alone
        "B02001_005E",  # Asian alone
        "B02001_006E",  # Native Hawaiian/Pacific Islander alone
        "B02001_007E",  # Some other race alone
        "B02001_008E",  # Two or more races
    ],
    "ethnicity": [
        "B03003_001E",  # Total
        "B03003_003E",  # Hispanic or Latino
    ],
}

VARIABLE_LABELS = {
    "B01003_001E": "Total Population",
    "B19013_001E": "Median Household Income",
    "B17001_001E": "Poverty Universe Total",
    "B17001_002E": "Below Poverty Level",
    "B15003_001E": "Educational Attainment Total (25+)",
    "B15003_022E": "Bachelor's Degree",
    "B15003_023E": "Master's Degree",
    "B15003_024E": "Professional School Degree",
    "B15003_025E": "Doctorate Degree",
    "B02001_001E": "Race Total",
    "B02001_002E": "White Alone",
    "B02001_003E": "Black or African American Alone",
    "B02001_004E": "American Indian and Alaska Native Alone",
    "B02001_005E": "Asian Alone",
    "B02001_006E": "Native Hawaiian and Other Pacific Islander Alone",
    "B02001_007E": "Some Other Race Alone",
    "B02001_008E": "Two or More Races",
    "B03003_001E": "Hispanic/Latino Origin Total",
    "B03003_003E": "Hispanic or Latino",
}

# Census sentinel values that mean "data not available"
SENTINEL_VALUES = {-666666666, -999999999, -888888888, -222222222, -333333333}

BASE_URL = "https://api.census.gov/data/{year}/acs/{estimate_type}"


class CensusACSClient:
    """Client for fetching data from the Census American Community Survey API."""

    def __init__(
        self,
        api_key: str | None = None,
        year: int = 2023,
        estimate_type: str = "acs1",
    ):
        self.api_key = api_key or os.getenv("CENSUS_API_KEY")
        # Census API works without a key for low-volume requests
        self.year = year
        self.estimate_type = estimate_type

    def _get_variables(self, groups: list[str] | None = None) -> list[str]:
        """Collect variable codes for the requested groups."""
        if groups is None:
            groups = list(VARIABLE_GROUPS.keys())
        variables = []
        for group in groups:
            if group not in VARIABLE_GROUPS:
                raise CensusAPIError(f"Unknown variable group: '{group}'")
            variables.extend(VARIABLE_GROUPS[group])
        return variables

    def fetch(
        self,
        state_fips: str,
        place_fips: str,
        groups: list[str] | None = None,
    ) -> dict[str, float | None]:
        """Fetch ACS data for a specific place.

        Returns:
            dict mapping variable code to value (float or None if unavailable)
        """
        variables = self._get_variables(groups)
        var_str = ",".join(variables)

        url = BASE_URL.format(year=self.year, estimate_type=self.estimate_type)
        params = {
            "get": f"NAME,{var_str}",
            "for": f"place:{place_fips}",
            "in": f"state:{state_fips}",
        }
        if self.api_key:
            params["key"] = self.api_key

        logger.info("Fetching ACS %s %d for state=%s place=%s", self.estimate_type, self.year, state_fips, place_fips)

        try:
            resp = requests.get(url, params=params, timeout=30)
        except requests.RequestException as e:
            raise CensusAPIError(f"Request failed: {e}") from e

        if resp.status_code == 204 or not resp.text.strip():
            # Try ACS5 fallback if we were using ACS1
            if self.estimate_type == "acs1":
                logger.info("ACS1 returned no data, falling back to ACS5")
                return self._fetch_acs5_fallback(state_fips, place_fips, groups)
            raise CensusAPIError(f"No data returned for state={state_fips} place={place_fips}")

        if resp.status_code != 200:
            if resp.status_code in (404, 400) and self.estimate_type == "acs1":
                logger.info("ACS1 returned %d, falling back to ACS5", resp.status_code)
                return self._fetch_acs5_fallback(state_fips, place_fips, groups)
            raise CensusAPIError(f"Census API error {resp.status_code}: {resp.text[:200]}")

        try:
            data = resp.json()
        except Exception as e:
            raise CensusAPIError(f"Invalid JSON response: {e}") from e

        if len(data) < 2:
            if self.estimate_type == "acs1":
                logger.info("ACS1 returned no data rows, falling back to ACS5")
                return self._fetch_acs5_fallback(state_fips, place_fips, groups)
            raise CensusAPIError("Census API returned headers but no data")

        headers = data[0]
        values = data[1]

        result = {}
        for var_code in variables:
            if var_code in headers:
                idx = headers.index(var_code)
                raw_val = values[idx]
                result[var_code] = self._parse_value(raw_val)
            else:
                result[var_code] = None

        return result

    def _fetch_acs5_fallback(
        self,
        state_fips: str,
        place_fips: str,
        groups: list[str] | None,
    ) -> dict[str, float | None]:
        """Retry the fetch using ACS 5-year estimates."""
        fallback = CensusACSClient(
            api_key=self.api_key,
            year=self.year,
            estimate_type="acs5",
        )
        return fallback.fetch(state_fips, place_fips, groups)

    @staticmethod
    def _parse_value(raw) -> float | None:
        """Convert a Census API value to float, handling sentinels and nulls."""
        if raw is None:
            return None
        try:
            val = float(raw)
        except (ValueError, TypeError):
            return None
        if val in SENTINEL_VALUES:
            return None
        return val

    def fetch_and_store(
        self,
        session,
        resolver_result: dict,
        groups: list[str] | None = None,
    ) -> dict[str, float | None]:
        """Fetch ACS data and persist to the database.

        Checks the DB cache first; only calls the API if data is missing.

        Args:
            session: SQLAlchemy session
            resolver_result: dict from FIPSResolver.resolve()
            groups: list of variable group names, or None for all

        Returns:
            dict mapping variable code to value
        """
        city = upsert_city(session, resolver_result)
        variables = self._get_variables(groups)

        # Check cache
        existing = get_acs_data(session, city.id, self.year)
        existing_codes = {r.variable_code for r in existing}
        missing = [v for v in variables if v not in existing_codes]

        if not missing:
            logger.info("All %d variables cached for city_id=%d year=%d", len(variables), city.id, self.year)
            return {r.variable_code: r.value for r in existing if r.variable_code in variables}

        # Fetch from API (fetch all requested, not just missing, since it's a single call)
        raw = self.fetch(resolver_result["state_fips"], resolver_result["place_fips"], groups)

        # Determine which estimate type was actually used
        est_type = self.estimate_type

        # Store all results
        for var_code, value in raw.items():
            upsert_acs_data(
                session=session,
                city_id=city.id,
                year=self.year,
                estimate_type=est_type,
                variable_code=var_code,
                variable_label=VARIABLE_LABELS.get(var_code),
                value=value,
            )
        session.commit()
        logger.info("Stored %d variables for %s", len(raw), resolver_result["city_name"])
        return raw

    @staticmethod
    def compute_derived(raw: dict[str, float | None]) -> dict[str, float | None]:
        """Compute derived metrics from raw ACS values.

        Returns:
            dict with keys like poverty_rate, bachelors_plus_pct, pct_white, etc.
        """
        derived = {}

        # Poverty rate
        poverty_total = raw.get("B17001_001E")
        poverty_below = raw.get("B17001_002E")
        if poverty_total and poverty_total > 0 and poverty_below is not None:
            derived["poverty_rate"] = round(poverty_below / poverty_total * 100, 2)
        else:
            derived["poverty_rate"] = None

        # Educational attainment: bachelor's degree or higher
        edu_total = raw.get("B15003_001E")
        if edu_total and edu_total > 0:
            bachelors_plus = sum(
                raw.get(v, 0) or 0
                for v in ["B15003_022E", "B15003_023E", "B15003_024E", "B15003_025E"]
            )
            derived["bachelors_plus_pct"] = round(bachelors_plus / edu_total * 100, 2)
        else:
            derived["bachelors_plus_pct"] = None

        # Racial composition percentages
        race_total = raw.get("B02001_001E")
        race_map = {
            "pct_white": "B02001_002E",
            "pct_black": "B02001_003E",
            "pct_native": "B02001_004E",
            "pct_asian": "B02001_005E",
            "pct_pacific_islander": "B02001_006E",
            "pct_other_race": "B02001_007E",
            "pct_two_or_more": "B02001_008E",
        }
        for key, var_code in race_map.items():
            val = raw.get(var_code)
            if race_total and race_total > 0 and val is not None:
                derived[key] = round(val / race_total * 100, 2)
            else:
                derived[key] = None

        # Hispanic/Latino percentage
        eth_total = raw.get("B03003_001E")
        eth_hispanic = raw.get("B03003_003E")
        if eth_total and eth_total > 0 and eth_hispanic is not None:
            derived["pct_hispanic"] = round(eth_hispanic / eth_total * 100, 2)
        else:
            derived["pct_hispanic"] = None

        return derived
