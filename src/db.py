"""Database session management and CRUD operations."""

import logging
import os
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import AcsData, Base, City

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
