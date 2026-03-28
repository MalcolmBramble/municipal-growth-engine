"""City data aggregator — single entry point that calls all data sources."""

import logging
from dataclasses import dataclass, field

from ..db import get_engine, get_session, init_db, upsert_city
from ..resolver import FIPSResolver
from .census import CensusACSClient
from .bls import BLSClient
from .housing import HousingDataClient
from .walkscore import WalkScoreClient
from .fema_nri import FEMANRIClient
from .fbi_crime import FBICrimeClient

logger = logging.getLogger(__name__)


@dataclass
class CityDataProfile:
    """Unified data profile for a city across all data sources."""

    city_name: str
    state_abbr: str
    state_fips: str
    place_fips: str

    # Census
    population: float | None = None
    population_growth_rate: float | None = None
    median_income: float | None = None
    poverty_rate: float | None = None
    bachelors_plus_pct: float | None = None
    racial_composition: dict[str, float] = field(default_factory=dict)

    # BLS
    unemployment_rate: float | None = None
    unemployment_trend: float | None = None

    # Housing
    median_sale_price: float | None = None
    price_yoy_change: float | None = None
    price_to_income_ratio: float | None = None
    median_dom: float | None = None
    months_of_supply: float | None = None
    zhvi: float | None = None
    zhvi_yoy_change: float | None = None

    # Walk Score
    walk_score: int | None = None
    transit_score: int | None = None
    bike_score: int | None = None

    # Climate/FEMA
    risk_rating: str | None = None
    risk_score: float | None = None
    hazard_scores: dict[str, str] = field(default_factory=dict)

    # Crime/FBI
    violent_crime_rate: float | None = None
    violent_crime_trend: float | None = None
    homicide_count: int | None = None
    homicide_trend_pct: float | None = None


class CityDataAggregator:
    """Aggregates data from all sources into a unified CityDataProfile."""

    def __init__(
        self,
        resolver: FIPSResolver | None = None,
        census_client: CensusACSClient | None = None,
        bls_client: BLSClient | None = None,
        housing_client: HousingDataClient | None = None,
        walkscore_client: WalkScoreClient | None = None,
        fema_client: FEMANRIClient | None = None,
        fbi_client: FBICrimeClient | None = None,
        db_path: str | None = None,
    ):
        self.resolver = resolver or FIPSResolver()
        self.census_client = census_client or CensusACSClient()
        self.bls_client = bls_client or BLSClient()
        self.housing_client = housing_client or HousingDataClient()
        self.walkscore_client = walkscore_client or WalkScoreClient()
        self.fema_client = fema_client or FEMANRIClient()
        self.fbi_client = fbi_client

        engine = get_engine(db_path)
        init_db(engine)
        self._session = get_session(engine)

    def aggregate(self, city_state: str) -> CityDataProfile:
        """Resolve a city and fetch data from all sources.

        Args:
            city_state: e.g. "Columbus, OH"

        Returns:
            CityDataProfile with all available data populated
        """
        # Resolve city
        resolved = self.resolver.resolve(city_state)
        profile = CityDataProfile(
            city_name=resolved["city_name"],
            state_abbr=resolved["state_abbr"],
            state_fips=resolved["state_fips"],
            place_fips=resolved["place_fips"],
        )

        # Census ACS data
        self._fetch_census(profile, resolved)

        # BLS unemployment
        self._fetch_bls(profile, resolved)

        # Housing data
        self._fetch_housing(profile, resolved)

        # Walk Score
        self._fetch_walkscore(profile, resolved)

        # FEMA NRI
        self._fetch_fema(profile, resolved)

        # FBI Crime
        self._fetch_crime(profile, resolved)

        # Derived cross-source metrics
        if profile.median_sale_price and profile.median_income and profile.median_income > 0:
            profile.price_to_income_ratio = round(
                profile.median_sale_price / profile.median_income, 2
            )

        return profile

    def _fetch_census(self, profile: CityDataProfile, resolved: dict) -> None:
        """Populate Census ACS fields on the profile."""
        try:
            raw = self.census_client.fetch_and_store(self._session, resolved)
            derived = CensusACSClient.compute_derived(raw)

            profile.population = raw.get("B01003_001E")
            profile.median_income = raw.get("B19013_001E")
            profile.poverty_rate = derived.get("poverty_rate")
            profile.bachelors_plus_pct = derived.get("bachelors_plus_pct")
            profile.racial_composition = {
                k: v for k, v in derived.items()
                if k.startswith("pct_") and v is not None
            }

            # Fetch prior-year population for growth rate
            prior_year = self.census_client.year - 5
            prior_client = CensusACSClient(
                api_key=self.census_client.api_key,
                year=prior_year,
                estimate_type="acs5",
            )
            try:
                prior_raw = prior_client.fetch_and_store(
                    self._session, resolved, groups=["population"],
                )
                prior_pop = prior_raw.get("B01003_001E")
                profile.population_growth_rate = CensusACSClient.compute_population_growth(
                    profile.population, prior_pop, years=5,
                )
            except Exception as e:
                logger.warning("Prior-year population fetch failed: %s", e)
        except Exception as e:
            logger.error("Census data fetch failed: %s", e)

    def _fetch_bls(self, profile: CityDataProfile, resolved: dict) -> None:
        """Populate BLS unemployment fields on the profile."""
        try:
            result = self.bls_client.fetch_and_store(self._session, resolved)
            profile.unemployment_rate = result.get("unemployment_rate")
            profile.unemployment_trend = result.get("unemployment_trend")
        except Exception as e:
            logger.error("BLS data fetch failed: %s", e)

    def _fetch_housing(self, profile: CityDataProfile, resolved: dict) -> None:
        """Populate housing data fields on the profile."""
        try:
            result = self.housing_client.fetch_and_store(self._session, resolved)
            profile.median_sale_price = result.get("redfin_median_sale_price")
            profile.price_yoy_change = result.get("redfin_median_sale_price_yoy")
            profile.median_dom = result.get("redfin_median_dom")
            profile.months_of_supply = result.get("redfin_months_of_supply")
            profile.zhvi = result.get("zillow_zhvi")
            profile.zhvi_yoy_change = result.get("zillow_zhvi_yoy_change")
        except Exception as e:
            logger.error("Housing data fetch failed: %s", e)

    def _fetch_walkscore(self, profile: CityDataProfile, resolved: dict) -> None:
        """Populate Walk Score fields on the profile."""
        try:
            result = self.walkscore_client.fetch_and_store(self._session, resolved)
            profile.walk_score = result.get("walk_score")
            profile.transit_score = result.get("transit_score")
            profile.bike_score = result.get("bike_score")
        except Exception as e:
            logger.error("Walk Score fetch failed: %s", e)

    def _fetch_fema(self, profile: CityDataProfile, resolved: dict) -> None:
        """Populate FEMA NRI fields on the profile."""
        try:
            result = self.fema_client.fetch_and_store(self._session, resolved)
            profile.risk_rating = result.get("risk_rating")
            profile.risk_score = result.get("risk_score")
            profile.hazard_scores = result.get("hazard_scores", {})
        except Exception as e:
            logger.error("FEMA NRI fetch failed: %s", e)

    def _fetch_crime(self, profile: CityDataProfile, resolved: dict) -> None:
        """Populate FBI crime data fields on the profile."""
        if self.fbi_client is None:
            return
        try:
            result = self.fbi_client.fetch_and_store(self._session, resolved)
            profile.violent_crime_rate = result.get("violent_crime_rate")
            profile.violent_crime_trend = result.get("violent_crime_trend")
            profile.homicide_count = result.get("homicide_count")
            profile.homicide_trend_pct = result.get("homicide_trend_pct")
        except Exception as e:
            logger.error("FBI crime data fetch failed: %s", e)
