"""Shared test fixtures."""

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db import init_db
from src.models import Base


@pytest.fixture
def db_engine():
    """In-memory SQLite engine with tables created."""
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    """Database session that rolls back after each test."""
    session = sessionmaker(bind=db_engine)()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def census_api_key():
    """Return the Census API key from environment, or skip if not set."""
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "config", ".env"))
    key = os.getenv("CENSUS_API_KEY")
    if not key:
        pytest.skip("CENSUS_API_KEY not set")
    return key


MOCK_CENSUS_RESPONSE = [
    ["NAME", "B01003_001E", "B19013_001E", "B17001_001E", "B17001_002E",
     "B15003_001E", "B15003_022E", "B15003_023E", "B15003_024E", "B15003_025E",
     "B02001_001E", "B02001_002E", "B02001_003E", "B02001_004E", "B02001_005E",
     "B02001_006E", "B02001_007E", "B02001_008E",
     "B03003_001E", "B03003_003E",
     "state", "place"],
    ["Columbus city, Ohio", "905748", "58326", "800000", "144000",
     "600000", "150000", "60000", "12000", "18000",
     "905748", "480000", "270000", "3000", "60000",
     "1000", "30000", "61748",
     "905748", "63000",
     "39", "18000"],
]
