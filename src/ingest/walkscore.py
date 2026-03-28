"""Walk Score API client — fetches walkability, transit, and bike scores."""

import logging
import os
from datetime import datetime, timezone

import requests

from ..db import upsert_city, upsert_walkscore_data, get_walkscore_data
from ..exceptions import WalkScoreError

logger = logging.getLogger(__name__)

WALKSCORE_URL = "https://api.walkscore.com/score"
GEOCODER_URL = "https://geocoding.geo.census.gov/geocoder/locations/address"


class WalkScoreClient:
    """Client for geocoding cities and fetching Walk Score data."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("WALKSCORE_API_KEY")

    def geocode(self, city_name: str, state_abbr: str) -> tuple[float, float]:
        """Geocode a city to lat/lon using the Census Geocoder.

        Returns:
            (latitude, longitude) tuple
        """
        # Strip Census suffixes for cleaner geocoding
        clean_name = city_name
        for suffix in (" city", " town", " village", " CDP", " borough", " municipality"):
            if clean_name.lower().endswith(suffix):
                clean_name = clean_name[:-len(suffix)]
                break

        params = {
            "city": clean_name,
            "state": state_abbr,
            "benchmark": "Public_AR_Current",
            "format": "json",
        }

        logger.info("Geocoding %s, %s via Census Geocoder", clean_name, state_abbr)

        try:
            resp = requests.get(GEOCODER_URL, params=params, timeout=15)
        except requests.RequestException as e:
            raise WalkScoreError(f"Geocoding request failed: {e}") from e

        if resp.status_code != 200:
            raise WalkScoreError(f"Geocoder error {resp.status_code}: {resp.text[:200]}")

        try:
            data = resp.json()
        except Exception as e:
            raise WalkScoreError(f"Invalid JSON from geocoder: {e}") from e

        matches = data.get("result", {}).get("addressMatches", [])
        if not matches:
            raise WalkScoreError(f"No geocoding results for {clean_name}, {state_abbr}")

        coords = matches[0].get("coordinates", {})
        lat = coords.get("y")
        lon = coords.get("x")
        if lat is None or lon is None:
            raise WalkScoreError("Geocoder returned no coordinates")

        logger.info("Geocoded to lat=%s, lon=%s", lat, lon)
        return float(lat), float(lon)

    def fetch(self, city_name: str, state_abbr: str) -> dict[str, int | None]:
        """Fetch Walk Score, Transit Score, and Bike Score for a city.

        Returns:
            dict with keys: walk_score, transit_score, bike_score
        """
        if not self.api_key:
            raise WalkScoreError("WALKSCORE_API_KEY not set")

        lat, lon = self.geocode(city_name, state_abbr)

        address = f"{city_name}, {state_abbr}"
        params = {
            "format": "json",
            "address": address,
            "lat": lat,
            "lon": lon,
            "transit": 1,
            "bike": 1,
            "wsapikey": self.api_key,
        }

        logger.info("Fetching Walk Score for %s", address)

        try:
            resp = requests.get(WALKSCORE_URL, params=params, timeout=15)
        except requests.RequestException as e:
            raise WalkScoreError(f"Walk Score request failed: {e}") from e

        if resp.status_code != 200:
            raise WalkScoreError(f"Walk Score API error {resp.status_code}: {resp.text[:200]}")

        try:
            data = resp.json()
        except Exception as e:
            raise WalkScoreError(f"Invalid JSON from Walk Score: {e}") from e

        if data.get("status") != 1:
            raise WalkScoreError(f"Walk Score API returned status {data.get('status')}: {data.get('description', '')}")

        return {
            "walk_score": data.get("walkscore"),
            "transit_score": data.get("transit", {}).get("score") if isinstance(data.get("transit"), dict) else None,
            "bike_score": data.get("bike", {}).get("score") if isinstance(data.get("bike"), dict) else None,
        }

    def fetch_and_store(
        self,
        session,
        resolver_result: dict,
        max_age_days: int = 90,
    ) -> dict[str, int | None]:
        """Fetch Walk Score data and persist to database.

        Checks cache first; re-fetches if data is stale.
        """
        city = upsert_city(session, resolver_result)

        # Check cache
        existing = get_walkscore_data(session, city.id)
        if existing:
            age = (datetime.now(timezone.utc).replace(tzinfo=None) - existing.fetched_at).days
            if age <= max_age_days:
                logger.info("Walk Score data cached for city_id=%d (age: %dd)", city.id, age)
                return {
                    "walk_score": existing.walk_score,
                    "transit_score": existing.transit_score,
                    "bike_score": existing.bike_score,
                }
            logger.info("Walk Score cache stale (%d days), re-fetching", age)

        # Fetch from API
        result = self.fetch(resolver_result["city_name"], resolver_result["state_abbr"])

        # Store
        upsert_walkscore_data(
            session=session,
            city_id=city.id,
            walk_score=result["walk_score"],
            transit_score=result["transit_score"],
            bike_score=result["bike_score"],
        )
        session.commit()
        logger.info("Stored Walk Score data for %s", resolver_result["city_name"])
        return result
