"""Tests for the database layer."""

from src.db import get_acs_data, upsert_acs_data, upsert_city


class TestUpsertCity:
    def test_creates_new_city(self, db_session):
        result = {"city_name": "Columbus city", "state_abbr": "OH", "state_fips": "39", "place_fips": "18000"}
        city = upsert_city(db_session, result)
        assert city.id is not None
        assert city.name == "Columbus city"
        assert city.state_fips == "39"
        assert city.place_fips == "18000"

    def test_upsert_idempotent(self, db_session):
        result = {"city_name": "Columbus city", "state_abbr": "OH", "state_fips": "39", "place_fips": "18000"}
        city1 = upsert_city(db_session, result)
        city2 = upsert_city(db_session, result)
        assert city1.id == city2.id


class TestUpsertAcsData:
    def test_creates_record(self, db_session):
        city_result = {"city_name": "Columbus city", "state_abbr": "OH", "state_fips": "39", "place_fips": "18000"}
        city = upsert_city(db_session, city_result)

        record = upsert_acs_data(db_session, city.id, 2023, "acs1", "B01003_001E", "Total Population", 905748.0)
        assert record.id is not None
        assert record.value == 905748.0

    def test_upsert_updates_value(self, db_session):
        city_result = {"city_name": "Columbus city", "state_abbr": "OH", "state_fips": "39", "place_fips": "18000"}
        city = upsert_city(db_session, city_result)

        r1 = upsert_acs_data(db_session, city.id, 2023, "acs1", "B01003_001E", "Total Population", 900000.0)
        r2 = upsert_acs_data(db_session, city.id, 2023, "acs1", "B01003_001E", "Total Population", 910000.0)
        assert r1.id == r2.id
        assert r2.value == 910000.0


class TestGetAcsData:
    def test_retrieves_stored_data(self, db_session):
        city_result = {"city_name": "Columbus city", "state_abbr": "OH", "state_fips": "39", "place_fips": "18000"}
        city = upsert_city(db_session, city_result)
        upsert_acs_data(db_session, city.id, 2023, "acs1", "B01003_001E", "Total Population", 905748.0)
        upsert_acs_data(db_session, city.id, 2023, "acs1", "B19013_001E", "Median Income", 58326.0)

        records = get_acs_data(db_session, city.id, 2023, "acs1")
        assert len(records) == 2
        codes = {r.variable_code for r in records}
        assert "B01003_001E" in codes
        assert "B19013_001E" in codes

    def test_empty_for_missing_year(self, db_session):
        city_result = {"city_name": "Columbus city", "state_abbr": "OH", "state_fips": "39", "place_fips": "18000"}
        city = upsert_city(db_session, city_result)
        records = get_acs_data(db_session, city.id, 2022)
        assert len(records) == 0
