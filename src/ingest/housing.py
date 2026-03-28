"""Housing data parsers for Redfin TSV and Zillow CSV files."""

import logging
import os
from datetime import datetime, timezone

import pandas as pd

from ..db import upsert_city, upsert_housing_data, get_housing_data
from ..exceptions import HousingDataError

logger = logging.getLogger(__name__)

DEFAULT_REDFIN_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "redfin", "metro_market_tracker.tsv"
)
DEFAULT_ZILLOW_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "zillow",
    "Metro_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv",
)


def _fuzzy_match_region(city_name: str, state_abbr: str, regions: list[str]) -> str | None:
    """Find the best-matching region name for a city.

    Matches if the city name appears in the region name (case-insensitive).
    Prefers matches that also contain the state abbreviation.
    """
    city_lower = city_name.lower().replace(" city", "").replace(" town", "").strip()
    state_lower = state_abbr.lower()

    # First pass: match city AND state
    for region in regions:
        r_lower = region.lower()
        if city_lower in r_lower and state_lower in r_lower:
            return region

    # Second pass: match city name only
    for region in regions:
        if city_lower in region.lower():
            return region

    return None


class HousingDataClient:
    """Parser for Redfin TSV and Zillow CSV housing data files."""

    def __init__(
        self,
        redfin_path: str | None = None,
        zillow_path: str | None = None,
    ):
        self.redfin_path = redfin_path or DEFAULT_REDFIN_PATH
        self.zillow_path = zillow_path or DEFAULT_ZILLOW_PATH

    def parse_redfin(self, city_name: str, state_abbr: str) -> dict[str, float | None]:
        """Parse Redfin metro market tracker TSV for a city.

        Returns:
            dict with keys: median_sale_price, median_ppsf, homes_sold,
            inventory, months_of_supply, median_dom, avg_sale_to_list,
            period, and *_yoy variants.
        """
        if not os.path.exists(self.redfin_path):
            logger.warning("Redfin TSV not found at %s", self.redfin_path)
            return {}

        logger.info("Parsing Redfin data for %s, %s", city_name, state_abbr)

        try:
            df = pd.read_csv(self.redfin_path, sep="\t", dtype=str)
        except Exception as e:
            raise HousingDataError(f"Failed to read Redfin TSV: {e}") from e

        # Identify the region column (case-insensitive)
        region_col = None
        for col in df.columns:
            if col.lower() in ("region", "region_name"):
                region_col = col
                break
        if region_col is None:
            raise HousingDataError(f"No 'region' column found in Redfin TSV. Columns: {list(df.columns)}")

        regions = df[region_col].dropna().unique().tolist()
        matched = _fuzzy_match_region(city_name, state_abbr, regions)
        if matched is None:
            logger.warning("No Redfin region match for %s, %s", city_name, state_abbr)
            return {}

        metro_df = df[df[region_col] == matched].copy()
        if metro_df.empty:
            return {}

        # Find date/period column
        period_col = None
        for col in metro_df.columns:
            if col.lower() in ("period_begin", "period_end", "month_date_yyyymm"):
                period_col = col
                break
        if period_col is None:
            period_col = metro_df.columns[-1]  # Fallback

        metro_df[period_col] = pd.to_datetime(metro_df[period_col], errors="coerce")
        metro_df = metro_df.dropna(subset=[period_col]).sort_values(period_col, ascending=False)

        if metro_df.empty:
            return {}

        # Most recent row
        latest = metro_df.iloc[0]
        period_str = latest[period_col].strftime("%Y-%m")

        # Same month prior year
        target_date = latest[period_col] - pd.DateOffset(years=1)
        prior_mask = (metro_df[period_col] >= target_date - pd.Timedelta(days=45)) & \
                     (metro_df[period_col] <= target_date + pd.Timedelta(days=45))
        prior_df = metro_df[prior_mask]

        metrics = {}
        metric_cols = {
            "median_sale_price": ["median_sale_price"],
            "median_ppsf": ["median_ppsf", "median_sale_price_per_sqft"],
            "homes_sold": ["homes_sold"],
            "inventory": ["inventory", "active_listings"],
            "months_of_supply": ["months_of_supply"],
            "median_dom": ["median_dom", "median_days_on_market"],
            "avg_sale_to_list": ["avg_sale_to_list", "sale_to_list_price"],
        }

        for metric_name, possible_cols in metric_cols.items():
            val = self._find_col_value(latest, possible_cols, metro_df.columns)
            metrics[metric_name] = val
            metrics[f"{metric_name}_period"] = period_str

            # YoY change
            if not prior_df.empty and val is not None:
                prior_val = self._find_col_value(prior_df.iloc[0], possible_cols, metro_df.columns)
                if prior_val is not None and prior_val != 0:
                    metrics[f"{metric_name}_yoy"] = round((val - prior_val) / prior_val * 100, 2)
                else:
                    metrics[f"{metric_name}_yoy"] = None
            else:
                metrics[f"{metric_name}_yoy"] = None

        metrics["period"] = period_str
        return metrics

    def parse_zillow(self, city_name: str, state_abbr: str) -> dict[str, float | None]:
        """Parse Zillow ZHVI CSV for a city.

        Returns:
            dict with keys: zhvi, zhvi_prior_year, zhvi_yoy_change, period
        """
        if not os.path.exists(self.zillow_path):
            logger.warning("Zillow CSV not found at %s", self.zillow_path)
            return {}

        logger.info("Parsing Zillow data for %s, %s", city_name, state_abbr)

        try:
            df = pd.read_csv(self.zillow_path, dtype={"RegionID": str})
        except Exception as e:
            raise HousingDataError(f"Failed to read Zillow CSV: {e}") from e

        # Find RegionName column
        region_col = None
        for col in df.columns:
            if col.lower() in ("regionname", "region_name"):
                region_col = col
                break
        if region_col is None:
            raise HousingDataError(f"No 'RegionName' column in Zillow CSV. Columns: {list(df.columns)}")

        regions = df[region_col].dropna().unique().tolist()
        matched = _fuzzy_match_region(city_name, state_abbr, regions)
        if matched is None:
            logger.warning("No Zillow region match for %s, %s", city_name, state_abbr)
            return {}

        row = df[df[region_col] == matched].iloc[0]

        # Date columns are like "2024-01-31"
        date_cols = [c for c in df.columns if c[:4].isdigit() and "-" in c]
        if not date_cols:
            raise HousingDataError("No date columns found in Zillow CSV")

        date_cols_sorted = sorted(date_cols, reverse=True)

        # Most recent ZHVI value
        zhvi = None
        period = None
        for col in date_cols_sorted:
            try:
                val = float(row[col])
                zhvi = val
                period = col[:7]  # "2024-01"
                break
            except (ValueError, TypeError):
                continue

        if zhvi is None:
            return {}

        # Prior year value
        zhvi_prior = None
        prior_target = str(int(period[:4]) - 1) + period[4:]
        for col in date_cols_sorted:
            if col.startswith(prior_target):
                try:
                    zhvi_prior = float(row[col])
                    break
                except (ValueError, TypeError):
                    continue

        yoy = None
        if zhvi_prior is not None and zhvi_prior != 0:
            yoy = round((zhvi - zhvi_prior) / zhvi_prior * 100, 2)

        return {
            "zhvi": zhvi,
            "zhvi_prior_year": zhvi_prior,
            "zhvi_yoy_change": yoy,
            "period": period,
        }

    def fetch_and_store(
        self,
        session,
        resolver_result: dict,
        max_age_days: int = 90,
    ) -> dict:
        """Parse both Redfin and Zillow data and persist to database.

        Checks cache first; re-parses if data is stale.
        """
        city = upsert_city(session, resolver_result)
        city_name = resolver_result["city_name"]
        state_abbr = resolver_result["state_abbr"]

        # Check cache
        existing = get_housing_data(session, city.id)
        if existing:
            newest = max(existing, key=lambda r: r.fetched_at)
            age = (datetime.now(timezone.utc).replace(tzinfo=None) - newest.fetched_at).days
            if age <= max_age_days:
                logger.info("Housing data cached for city_id=%d (age: %dd)", city.id, age)
                result = {}
                for rec in existing:
                    result[f"{rec.source}_{rec.metric_name}"] = rec.metric_value
                return result
            logger.info("Housing cache stale (%d days), re-parsing", age)

        combined = {}

        # Parse Redfin
        redfin = self.parse_redfin(city_name, state_abbr)
        for key, val in redfin.items():
            if key.endswith("_period") or key == "period":
                continue
            period = redfin.get("period", "unknown")
            if isinstance(val, (int, float)):
                upsert_housing_data(session, city.id, "redfin", key, val, period)
            combined[f"redfin_{key}"] = val

        # Parse Zillow
        zillow = self.parse_zillow(city_name, state_abbr)
        for key, val in zillow.items():
            if key == "period":
                continue
            period = zillow.get("period", "unknown")
            if isinstance(val, (int, float)):
                upsert_housing_data(session, city.id, "zillow", key, val, period)
            combined[f"zillow_{key}"] = val

        session.commit()
        logger.info("Stored housing data for %s", city_name)
        return combined

    @staticmethod
    def _find_col_value(row, possible_names: list[str], columns) -> float | None:
        """Find a value in a row by trying multiple possible column names."""
        cols_lower = {c.lower(): c for c in columns}
        for name in possible_names:
            actual = cols_lower.get(name.lower())
            if actual and actual in row.index:
                try:
                    return float(row[actual])
                except (ValueError, TypeError):
                    continue
        return None
