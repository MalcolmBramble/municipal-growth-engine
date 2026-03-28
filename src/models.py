"""SQLAlchemy ORM models for municipal-growth-engine."""

from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Re-export for convenience
__all__ = [
    "Base", "City", "AcsData", "BLSData", "HousingData",
    "WalkScoreData", "ClimateRiskData", "CrimeData",
]


class Base(DeclarativeBase):
    pass


class City(Base):
    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    state_abbr: Mapped[str] = mapped_column(String(2), nullable=False)
    state_fips: Mapped[str] = mapped_column(String(2), nullable=False)
    place_fips: Mapped[str] = mapped_column(String(5), nullable=False)

    acs_data: Mapped[list["AcsData"]] = relationship(back_populates="city", cascade="all, delete-orphan")
    bls_data: Mapped[list["BLSData"]] = relationship(back_populates="city", cascade="all, delete-orphan")
    housing_data: Mapped[list["HousingData"]] = relationship(back_populates="city", cascade="all, delete-orphan")
    walkscore_data: Mapped[list["WalkScoreData"]] = relationship(back_populates="city", cascade="all, delete-orphan")
    climate_risk_data: Mapped[list["ClimateRiskData"]] = relationship(back_populates="city", cascade="all, delete-orphan")
    crime_data: Mapped[list["CrimeData"]] = relationship(back_populates="city", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("state_fips", "place_fips", name="uq_city_fips"),
    )

    def __repr__(self) -> str:
        return f"<City(name='{self.name}', state='{self.state_abbr}', fips='{self.state_fips}{self.place_fips}')>"


class AcsData(Base):
    __tablename__ = "acs_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    city_id: Mapped[int] = mapped_column(Integer, ForeignKey("cities.id"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    estimate_type: Mapped[str] = mapped_column(String(10), nullable=False)
    variable_code: Mapped[str] = mapped_column(String(20), nullable=False)
    variable_label: Mapped[str] = mapped_column(String(200), nullable=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    city: Mapped["City"] = relationship(back_populates="acs_data")

    __table_args__ = (
        UniqueConstraint("city_id", "year", "estimate_type", "variable_code", name="uq_acs_record"),
    )

    def __repr__(self) -> str:
        return f"<AcsData(city_id={self.city_id}, var='{self.variable_code}', value={self.value})>"


class BLSData(Base):
    __tablename__ = "bls_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    city_id: Mapped[int] = mapped_column(Integer, ForeignKey("cities.id"), nullable=False)
    series_id: Mapped[str] = mapped_column(String(30), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    period: Mapped[str] = mapped_column(String(5), nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    city: Mapped["City"] = relationship(back_populates="bls_data")

    __table_args__ = (
        UniqueConstraint("city_id", "series_id", "year", "period", name="uq_bls_record"),
    )

    def __repr__(self) -> str:
        return f"<BLSData(series='{self.series_id}', year={self.year}, period='{self.period}', value={self.value})>"


class HousingData(Base):
    __tablename__ = "housing_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    city_id: Mapped[int] = mapped_column(Integer, ForeignKey("cities.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(50), nullable=False)
    metric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    period: Mapped[str] = mapped_column(String(10), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    city: Mapped["City"] = relationship(back_populates="housing_data")

    __table_args__ = (
        UniqueConstraint("city_id", "source", "metric_name", "period", name="uq_housing_record"),
    )

    def __repr__(self) -> str:
        return f"<HousingData(source='{self.source}', metric='{self.metric_name}', value={self.metric_value})>"


class WalkScoreData(Base):
    __tablename__ = "walkscore_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    city_id: Mapped[int] = mapped_column(Integer, ForeignKey("cities.id"), nullable=False)
    walk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transit_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bike_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    city: Mapped["City"] = relationship(back_populates="walkscore_data")

    __table_args__ = (
        UniqueConstraint("city_id", name="uq_walkscore_city"),
    )

    def __repr__(self) -> str:
        return f"<WalkScoreData(city_id={self.city_id}, walk={self.walk_score}, transit={self.transit_score})>"


class ClimateRiskData(Base):
    __tablename__ = "climate_risk_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    city_id: Mapped[int] = mapped_column(Integer, ForeignKey("cities.id"), nullable=False)
    risk_rating: Mapped[str | None] = mapped_column(String(30), nullable=True)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    earthquake_risk: Mapped[str | None] = mapped_column(String(30), nullable=True)
    tornado_risk: Mapped[str | None] = mapped_column(String(30), nullable=True)
    hurricane_risk: Mapped[str | None] = mapped_column(String(30), nullable=True)
    wildfire_risk: Mapped[str | None] = mapped_column(String(30), nullable=True)
    flood_risk: Mapped[str | None] = mapped_column(String(30), nullable=True)
    heat_wave_risk: Mapped[str | None] = mapped_column(String(30), nullable=True)
    cold_wave_risk: Mapped[str | None] = mapped_column(String(30), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    city: Mapped["City"] = relationship(back_populates="climate_risk_data")

    __table_args__ = (
        UniqueConstraint("city_id", name="uq_climate_risk_city"),
    )

    def __repr__(self) -> str:
        return f"<ClimateRiskData(city_id={self.city_id}, rating='{self.risk_rating}')>"


class CrimeData(Base):
    __tablename__ = "crime_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    city_id: Mapped[int] = mapped_column(Integer, ForeignKey("cities.id"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    violent_crime_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    homicide_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    population: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data_source: Mapped[str] = mapped_column(String(20), nullable=False)  # "fbi_api" or "state_fallback"
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    city: Mapped["City"] = relationship(back_populates="crime_data")

    __table_args__ = (
        UniqueConstraint("city_id", "year", "data_source", name="uq_crime_record"),
    )

    def __repr__(self) -> str:
        return f"<CrimeData(city_id={self.city_id}, year={self.year}, violent_rate={self.violent_crime_rate})>"
