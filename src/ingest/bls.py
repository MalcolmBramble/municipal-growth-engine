"""BLS Public Data API client — fetches unemployment data."""

import logging
import os
from datetime import datetime, timezone

import requests

from ..db import get_bls_data, upsert_bls_data, upsert_city
from ..exceptions import BLSAPIError

logger = logging.getLogger(__name__)

BASE_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"


def state_unemployment_series(state_fips: str) -> str:
    """Build BLS series ID for state-level unemployment rate."""
    return f"LASST{state_fips}0000000003"


class BLSClient:
    """Client for fetching unemployment data from the BLS API."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("BLS_API_KEY")

    def fetch(
        self,
        series_ids: list[str],
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> dict[str, list[dict]]:
        """Fetch time series data from BLS.

        Returns:
            dict mapping series_id to list of {year, period, value} dicts,
            sorted newest-first.
        """
        now_year = datetime.now().year
        if end_year is None:
            end_year = now_year
        if start_year is None:
            start_year = end_year - 1

        payload = {
            "seriesid": series_ids,
            "startyear": str(start_year),
            "endyear": str(end_year),
        }
        if self.api_key:
            payload["registrationkey"] = self.api_key

        logger.info("Fetching BLS series %s (%d-%d)", series_ids, start_year, end_year)

        try:
            resp = requests.post(BASE_URL, json=payload, timeout=30)
        except requests.RequestException as e:
            raise BLSAPIError(f"BLS request failed: {e}") from e

        if resp.status_code != 200:
            raise BLSAPIError(f"BLS API error {resp.status_code}: {resp.text[:200]}")

        try:
            data = resp.json()
        except Exception as e:
            raise BLSAPIError(f"Invalid JSON from BLS: {e}") from e

        if data.get("status") != "REQUEST_SUCCEEDED":
            msg = "; ".join(data.get("message", []))
            raise BLSAPIError(f"BLS API request failed: {msg}")

        results = {}
        for series in data.get("Results", {}).get("series", []):
            sid = series["seriesID"]
            points = []
            for item in series.get("data", []):
                try:
                    val = float(item["value"])
                except (ValueError, TypeError):
                    val = None
                points.append({
                    "year": int(item["year"]),
                    "period": item["period"],
                    "value": val,
                })
            # Sort by year desc, period desc (M12 > M01)
            points.sort(key=lambda p: (p["year"], p["period"]), reverse=True)
            results[sid] = points

        return results

    def fetch_unemployment(self, state_fips: str) -> dict:
        """Fetch state unemployment rate and compute YoY trend.

        Returns:
            dict with keys: unemployment_rate, unemployment_prior_year,
            unemployment_trend (YoY change in percentage points), series_id
        """
        series_id = state_unemployment_series(state_fips)
        data = self.fetch([series_id])

        if series_id not in data or not data[series_id]:
            raise BLSAPIError(f"No data returned for series {series_id}")

        points = data[series_id]

        # Find most recent monthly value (skip annual periods like M13)
        current = None
        for p in points:
            if p["period"].startswith("M") and p["period"] != "M13" and p["value"] is not None:
                current = p
                break

        if current is None:
            raise BLSAPIError(f"No monthly data found for series {series_id}")

        # Find same month from prior year
        prior = None
        for p in points:
            if (p["period"] == current["period"]
                    and p["year"] == current["year"] - 1
                    and p["value"] is not None):
                prior = p
                break

        trend = None
        if prior is not None and prior["value"] is not None:
            trend = round(current["value"] - prior["value"], 2)

        return {
            "series_id": series_id,
            "unemployment_rate": current["value"],
            "unemployment_year": current["year"],
            "unemployment_period": current["period"],
            "unemployment_prior_year": prior["value"] if prior else None,
            "unemployment_trend": trend,
        }

    def fetch_and_store(
        self,
        session,
        resolver_result: dict,
    ) -> dict:
        """Fetch BLS unemployment data and persist to database.

        Checks cache first; only calls API if data is missing.
        """
        city = upsert_city(session, resolver_result)
        series_id = state_unemployment_series(resolver_result["state_fips"])

        # Check cache
        existing = get_bls_data(session, city.id, series_id)
        if existing:
            logger.info("BLS data cached for city_id=%d series=%s", city.id, series_id)
            # Reconstruct result from cached data
            points = sorted(existing, key=lambda r: (r.year, r.period), reverse=True)
            current = None
            for p in points:
                if p.period.startswith("M") and p.period != "M13" and p.value is not None:
                    current = p
                    break
            if current:
                prior = None
                for p in points:
                    if p.period == current.period and p.year == current.year - 1 and p.value is not None:
                        prior = p
                        break
                trend = round(current.value - prior.value, 2) if prior else None
                return {
                    "series_id": series_id,
                    "unemployment_rate": current.value,
                    "unemployment_year": current.year,
                    "unemployment_period": current.period,
                    "unemployment_prior_year": prior.value if prior else None,
                    "unemployment_trend": trend,
                }

        # Fetch from API
        result = self.fetch_unemployment(resolver_result["state_fips"])

        # Store all raw data points
        raw_data = self.fetch([series_id])
        for point in raw_data.get(series_id, []):
            upsert_bls_data(
                session=session,
                city_id=city.id,
                series_id=series_id,
                year=point["year"],
                period=point["period"],
                value=point["value"],
            )
        session.commit()
        logger.info("Stored BLS data for %s", resolver_result["city_name"])
        return result
