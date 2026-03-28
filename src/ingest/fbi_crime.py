"""FBI Crime Data Explorer API client — fetches violent crime and homicide data."""

import logging
import os

import requests

from ..db import upsert_city, upsert_crime_data, get_crime_data
from ..exceptions import FBICrimeError

logger = logging.getLogger(__name__)

BASE_URL = "https://api.usa.gov/crime/fbi/cde"


class FBICrimeClient:
    """Client for fetching crime data from the FBI Crime Data Explorer API.

    Tries agency-level data first (by ORI), falls back to state-level estimates.
    """

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("FBI_API_KEY")
        if not self.api_key:
            raise FBICrimeError(
                "FBI_API_KEY not set. Get one free at https://api.data.gov/signup/"
            )

    def _get(self, endpoint: str, params: dict | None = None) -> dict | list:
        """Make a GET request to the FBI CDE API."""
        url = f"{BASE_URL}/{endpoint}"
        p = params or {}
        p["API_KEY"] = self.api_key

        logger.info("FBI API GET %s", endpoint)

        try:
            resp = requests.get(url, params=p, timeout=30)
        except requests.RequestException as e:
            raise FBICrimeError(f"FBI API request failed: {e}") from e

        if resp.status_code != 200:
            raise FBICrimeError(f"FBI API error {resp.status_code}: {resp.text[:200]}")

        try:
            return resp.json()
        except Exception as e:
            raise FBICrimeError(f"Invalid JSON from FBI API: {e}") from e

    def fetch_state_estimates(
        self, state_abbr: str, start_year: int = 2020, end_year: int = 2023,
    ) -> list[dict]:
        """Fetch state-level crime estimates.

        The /estimate/state/{abbr} endpoint returns yearly estimates including
        violent crime totals and homicide counts.

        Returns:
            list of dicts with keys: year, population, violent_crime, homicides, violent_crime_rate
        """
        endpoint = f"estimate/state/{state_abbr}"
        params = {"from": start_year, "to": end_year}

        data = self._get(endpoint, params)

        if not isinstance(data, list) or not data:
            raise FBICrimeError(f"No state estimate data for {state_abbr}")

        results = []
        for entry in data:
            year = entry.get("year")
            population = entry.get("population")
            violent_crime = entry.get("violent_crime")
            homicides = entry.get("homicide")

            if year is None:
                continue

            rate = None
            if population and violent_crime is not None and population > 0:
                rate = round(violent_crime / population * 100000, 2)

            results.append({
                "year": year,
                "population": population,
                "violent_crime": violent_crime,
                "homicides": homicides,
                "violent_crime_rate": rate,
            })

        results.sort(key=lambda x: x["year"], reverse=True)
        return results

    def fetch_crime_data(self, state_abbr: str) -> dict:
        """Fetch crime data and compute trends.

        Returns:
            dict with keys: violent_crime_rate, violent_crime_rate_prior,
            violent_crime_trend, homicide_count, homicide_count_prior,
            homicide_trend, data_source, years
        """
        estimates = self.fetch_state_estimates(state_abbr)

        if len(estimates) < 1:
            raise FBICrimeError(f"Insufficient crime data for {state_abbr}")

        current = estimates[0]

        # Find prior year
        prior = None
        if len(estimates) >= 2:
            prior = estimates[1]

        result = {
            "violent_crime_rate": current.get("violent_crime_rate"),
            "homicide_count": current.get("homicides"),
            "current_year": current["year"],
            "population": current.get("population"),
            "data_source": "state_estimate",
        }

        if prior:
            result["violent_crime_rate_prior"] = prior.get("violent_crime_rate")
            result["homicide_count_prior"] = prior.get("homicides")

            # Compute YoY trends
            if result["violent_crime_rate"] is not None and prior.get("violent_crime_rate"):
                result["violent_crime_trend"] = round(
                    result["violent_crime_rate"] - prior["violent_crime_rate"], 2
                )
            else:
                result["violent_crime_trend"] = None

            if result["homicide_count"] is not None and prior.get("homicides") is not None:
                prior_h = prior["homicides"]
                if prior_h > 0:
                    result["homicide_trend_pct"] = round(
                        (result["homicide_count"] - prior_h) / prior_h * 100, 2
                    )
                else:
                    result["homicide_trend_pct"] = None
            else:
                result["homicide_trend_pct"] = None
        else:
            result["violent_crime_rate_prior"] = None
            result["homicide_count_prior"] = None
            result["violent_crime_trend"] = None
            result["homicide_trend_pct"] = None

        return result

    def fetch_and_store(self, session, resolver_result: dict) -> dict:
        """Fetch FBI crime data and persist to database.

        Checks cache first.
        """
        city = upsert_city(session, resolver_result)
        state_abbr = resolver_result["state_abbr"]

        # Check cache
        existing = get_crime_data(session, city.id)
        if existing:
            logger.info("Crime data cached for city_id=%d", city.id)
            records = sorted(existing, key=lambda r: r.year, reverse=True)
            current = records[0]
            prior = records[1] if len(records) >= 2 else None

            result = {
                "violent_crime_rate": current.violent_crime_rate,
                "homicide_count": current.homicide_count,
                "current_year": current.year,
                "population": current.population,
                "data_source": current.data_source,
                "violent_crime_rate_prior": prior.violent_crime_rate if prior else None,
                "homicide_count_prior": prior.homicide_count if prior else None,
            }

            if prior and current.violent_crime_rate and prior.violent_crime_rate:
                result["violent_crime_trend"] = round(
                    current.violent_crime_rate - prior.violent_crime_rate, 2
                )
            else:
                result["violent_crime_trend"] = None

            if prior and current.homicide_count is not None and prior.homicide_count:
                result["homicide_trend_pct"] = round(
                    (current.homicide_count - prior.homicide_count) / prior.homicide_count * 100, 2
                )
            else:
                result["homicide_trend_pct"] = None

            return result

        # Fetch from API
        result = self.fetch_crime_data(state_abbr)

        # Store all year estimates
        estimates = self.fetch_state_estimates(state_abbr)
        for est in estimates:
            upsert_crime_data(
                session=session,
                city_id=city.id,
                year=est["year"],
                violent_crime_rate=est.get("violent_crime_rate"),
                homicide_count=est.get("homicides"),
                population=est.get("population"),
                data_source="state_estimate",
            )
        session.commit()
        logger.info("Stored crime data for %s (%s)", resolver_result["city_name"], state_abbr)
        return result
