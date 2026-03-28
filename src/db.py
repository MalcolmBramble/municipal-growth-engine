"""Database session management and CRUD operations."""

import logging
import os
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import AcsData, BLSData, Base, City, ClimateRiskData, CrimeData, HousingData, WalkScoreData

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "census_tool.db")


def get_engine(db_path: str | None = None) -> Engine:
    """Create a SQLAlchemy engine for the given database path."""
    path = db_path or DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    return create_engine(f"sqlite:///{path}", echo=False)


def init_db(engine: Engine) -> None:
    """Create all tables if they don't exist."""
    Base.metadata.create_all(engine)
    logger.info("Database initialized")


def get_session(engine: Engine) -> Session:
    """Create and return a new database session."""
    return sessionmaker(bind=engine)()


def upsert_city(session: Session, resolver_result: dict) -> City:
    """Get or create a city record from resolver output.

    Args:
        resolver_result: dict with keys city_name, state_abbr, state_fips, place_fips
    """
    stmt = select(City).where(
        City.state_fips == resolver_result["state_fips"],
        City.place_fips == resolver_result["place_fips"],
    )
    city = session.execute(stmt).scalar_one_or_none()

    if city is None:
        city = City(
            name=resolver_result["city_name"],
            state_abbr=resolver_result["state_abbr"],
            state_fips=resolver_result["state_fips"],
            place_fips=resolver_result["place_fips"],
        )
        session.add(city)
        session.flush()
        logger.info("Created city record: %s", city)
    return city


def upsert_acs_data(
    session: Session,
    city_id: int,
    year: int,
    estimate_type: str,
    variable_code: str,
    variable_label: str | None,
    value: float | None,
) -> AcsData:
    """Insert or update an ACS data record."""
    stmt = select(AcsData).where(
        AcsData.city_id == city_id,
        AcsData.year == year,
        AcsData.estimate_type == estimate_type,
        AcsData.variable_code == variable_code,
    )
    record = session.execute(stmt).scalar_one_or_none()

    if record is None:
        record = AcsData(
            city_id=city_id,
            year=year,
            estimate_type=estimate_type,
            variable_code=variable_code,
            variable_label=variable_label,
            value=value,
            fetched_at=datetime.now(timezone.utc),
        )
        session.add(record)
    else:
        record.value = value
        record.variable_label = variable_label
        record.fetched_at = datetime.now(timezone.utc)
    session.flush()
    return record


def get_acs_data(
    session: Session,
    city_id: int,
    year: int,
    estimate_type: str | None = None,
) -> list[AcsData]:
    """Query stored ACS data for a city/year."""
    stmt = select(AcsData).where(AcsData.city_id == city_id, AcsData.year == year)
    if estimate_type:
        stmt = stmt.where(AcsData.estimate_type == estimate_type)
    return list(session.execute(stmt).scalars().all())


# ── BLS helpers ──────────────────────────────────────────────────────────────

def upsert_bls_data(
    session: Session,
    city_id: int,
    series_id: str,
    year: int,
    period: str,
    value: float | None,
) -> BLSData:
    """Insert or update a BLS data record."""
    stmt = select(BLSData).where(
        BLSData.city_id == city_id,
        BLSData.series_id == series_id,
        BLSData.year == year,
        BLSData.period == period,
    )
    record = session.execute(stmt).scalar_one_or_none()
    if record is None:
        record = BLSData(
            city_id=city_id, series_id=series_id, year=year,
            period=period, value=value, fetched_at=datetime.now(timezone.utc),
        )
        session.add(record)
    else:
        record.value = value
        record.fetched_at = datetime.now(timezone.utc)
    session.flush()
    return record


def get_bls_data(
    session: Session, city_id: int, series_id: str,
) -> list[BLSData]:
    """Query stored BLS data for a city/series."""
    stmt = select(BLSData).where(
        BLSData.city_id == city_id, BLSData.series_id == series_id,
    )
    return list(session.execute(stmt).scalars().all())


# ── Housing helpers ──────────────────────────────────────────────────────────

def upsert_housing_data(
    session: Session,
    city_id: int,
    source: str,
    metric_name: str,
    metric_value: float | None,
    period: str,
) -> HousingData:
    """Insert or update a housing data record."""
    stmt = select(HousingData).where(
        HousingData.city_id == city_id,
        HousingData.source == source,
        HousingData.metric_name == metric_name,
        HousingData.period == period,
    )
    record = session.execute(stmt).scalar_one_or_none()
    if record is None:
        record = HousingData(
            city_id=city_id, source=source, metric_name=metric_name,
            metric_value=metric_value, period=period,
            fetched_at=datetime.now(timezone.utc),
        )
        session.add(record)
    else:
        record.metric_value = metric_value
        record.fetched_at = datetime.now(timezone.utc)
    session.flush()
    return record


def get_housing_data(
    session: Session, city_id: int, source: str | None = None,
) -> list[HousingData]:
    """Query stored housing data for a city."""
    stmt = select(HousingData).where(HousingData.city_id == city_id)
    if source:
        stmt = stmt.where(HousingData.source == source)
    return list(session.execute(stmt).scalars().all())


# ── Walk Score helpers ───────────────────────────────────────────────────────

def upsert_walkscore_data(
    session: Session,
    city_id: int,
    walk_score: int | None,
    transit_score: int | None,
    bike_score: int | None,
) -> WalkScoreData:
    """Insert or update Walk Score data for a city."""
    stmt = select(WalkScoreData).where(WalkScoreData.city_id == city_id)
    record = session.execute(stmt).scalar_one_or_none()
    if record is None:
        record = WalkScoreData(
            city_id=city_id, walk_score=walk_score,
            transit_score=transit_score, bike_score=bike_score,
            fetched_at=datetime.now(timezone.utc),
        )
        session.add(record)
    else:
        record.walk_score = walk_score
        record.transit_score = transit_score
        record.bike_score = bike_score
        record.fetched_at = datetime.now(timezone.utc)
    session.flush()
    return record


def get_walkscore_data(session: Session, city_id: int) -> WalkScoreData | None:
    """Query stored Walk Score data for a city."""
    stmt = select(WalkScoreData).where(WalkScoreData.city_id == city_id)
    return session.execute(stmt).scalar_one_or_none()


# ── Climate Risk helpers ─────────────────────────────────────────────────────

def upsert_climate_risk_data(
    session: Session,
    city_id: int,
    risk_rating: str | None,
    risk_score: float | None,
    hazard_scores: dict[str, str | None],
) -> ClimateRiskData:
    """Insert or update climate risk data for a city."""
    stmt = select(ClimateRiskData).where(ClimateRiskData.city_id == city_id)
    record = session.execute(stmt).scalar_one_or_none()
    if record is None:
        record = ClimateRiskData(
            city_id=city_id, risk_rating=risk_rating, risk_score=risk_score,
            earthquake_risk=hazard_scores.get("earthquake"),
            tornado_risk=hazard_scores.get("tornado"),
            hurricane_risk=hazard_scores.get("hurricane"),
            wildfire_risk=hazard_scores.get("wildfire"),
            flood_risk=hazard_scores.get("flood"),
            heat_wave_risk=hazard_scores.get("heat_wave"),
            cold_wave_risk=hazard_scores.get("cold_wave"),
            fetched_at=datetime.now(timezone.utc),
        )
        session.add(record)
    else:
        record.risk_rating = risk_rating
        record.risk_score = risk_score
        record.earthquake_risk = hazard_scores.get("earthquake")
        record.tornado_risk = hazard_scores.get("tornado")
        record.hurricane_risk = hazard_scores.get("hurricane")
        record.wildfire_risk = hazard_scores.get("wildfire")
        record.flood_risk = hazard_scores.get("flood")
        record.heat_wave_risk = hazard_scores.get("heat_wave")
        record.cold_wave_risk = hazard_scores.get("cold_wave")
        record.fetched_at = datetime.now(timezone.utc)
    session.flush()
    return record


def get_climate_risk_data(session: Session, city_id: int) -> ClimateRiskData | None:
    """Query stored climate risk data for a city."""
    stmt = select(ClimateRiskData).where(ClimateRiskData.city_id == city_id)
    return session.execute(stmt).scalar_one_or_none()


# ── Crime Data helpers ───────────────────────────────────────────────────────

def upsert_crime_data(
    session: Session,
    city_id: int,
    year: int,
    violent_crime_rate: float | None,
    homicide_count: int | None,
    population: int | None,
    data_source: str,
) -> CrimeData:
    """Insert or update crime data for a city/year."""
    stmt = select(CrimeData).where(
        CrimeData.city_id == city_id,
        CrimeData.year == year,
        CrimeData.data_source == data_source,
    )
    record = session.execute(stmt).scalar_one_or_none()
    if record is None:
        record = CrimeData(
            city_id=city_id, year=year,
            violent_crime_rate=violent_crime_rate,
            homicide_count=homicide_count,
            population=population,
            data_source=data_source,
            fetched_at=datetime.now(timezone.utc),
        )
        session.add(record)
    else:
        record.violent_crime_rate = violent_crime_rate
        record.homicide_count = homicide_count
        record.population = population
        record.fetched_at = datetime.now(timezone.utc)
    session.flush()
    return record


def get_crime_data(
    session: Session, city_id: int, year: int | None = None,
) -> list[CrimeData]:
    """Query stored crime data for a city."""
    stmt = select(CrimeData).where(CrimeData.city_id == city_id)
    if year:
        stmt = stmt.where(CrimeData.year == year)
    return list(session.execute(stmt).scalars().all())
