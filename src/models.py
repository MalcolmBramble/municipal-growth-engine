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
