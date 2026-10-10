"""Weather: city lookup, forecast parsing, caching. No network."""

from datetime import datetime, timedelta, timezone

import pytest

from mindtrail.integrations.weather import WeatherClient, WeatherError, describe
from mindtrail.organize.app_state import AppState
from mindtrail.organize.db import initialize

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)

GEOCODE = {"results": [{"name": "Irvine", "admin1": "California", "latitude": 33.68, "longitude": -117.8}]}
FORECAST = {
    "current": {"temperature_2m": 71.6, "weather_code": 2},
    "daily": {"temperature_2m_max": [78.2], "temperature_2m_min": [58.4], "precipitation_probability_max": [10]},
}


@pytest.fixture
def state(tmp_path):
    db = str(tmp_path / "t.db")
    initialize(db)
    return AppState(db)


def fake_get(calls):
    def get(url, params):
        calls.append((url, params))
        return GEOCODE if "geocoding" in url else FORECAST
    return get


def test_a_city_becomes_coordinates_and_only_those_are_used_afterwards(state):
    calls = []
    client = WeatherClient(state, get=fake_get(calls), clock=lambda: NOW)

    place = client.set_city("Irvine")
    client.refresh()

    assert place == {"name": "Irvine, California", "lat": 33.68, "lon": -117.8}
    forecast_params = calls[-1][1]
    assert forecast_params["latitude"] == 33.68 and "Irvine" not in str(forecast_params)


def test_the_forecast_is_read_into_plain_numbers(state):
    client = WeatherClient(state, get=fake_get([]), clock=lambda: NOW)
    client.set_city("Irvine")

    client.refresh()
    out = client.cached()

    assert (out["temp"], out["high"], out["low"], out["rain"]) == (72, 78, 58, 10)
    assert out["summary"] == "Partly cloudy" and out["place"] == "Irvine, California"


def test_nothing_is_configured_until_a_city_is_set(state):
    assert WeatherClient(state, get=fake_get([])).cached() == {"configured": False}


def test_an_unknown_city_is_an_error_and_changes_nothing(state):
    client = WeatherClient(state, get=lambda url, params: {"results": []})

    with pytest.raises(ValueError):
        client.set_city("Nowheresville")
    assert client.place() == {}


def test_a_blank_city_clears_the_setting(state):
    client = WeatherClient(state, get=fake_get([]))
    client.set_city("Irvine")

    client.set_city("")

    assert client.cached() == {"configured": False}


def test_a_failed_refresh_keeps_the_last_good_numbers(state):
    client = WeatherClient(state, get=fake_get([]), clock=lambda: NOW)
    client.set_city("Irvine")
    client.refresh()

    def broken(url, params):
        raise WeatherError("offline")
    client._get = broken
    result = client.refresh()

    assert "offline" in result["error"]
    assert client.cached()["temp"] == 72


def test_the_cache_goes_stale_after_an_hour(state):
    clock = {"now": NOW}
    client = WeatherClient(state, get=fake_get([]), clock=lambda: clock["now"])
    client.set_city("Irvine")
    client.refresh()
    assert not client.stale()

    clock["now"] = NOW + timedelta(minutes=61)

    assert client.stale()


def test_changing_the_unit_asks_for_new_numbers(state):
    calls = []
    client = WeatherClient(state, get=fake_get(calls), clock=lambda: NOW)
    client.set_city("Irvine")
    client.set_unit("celsius")

    client.refresh()

    assert calls[-1][1]["temperature_unit"] == "celsius"
    with pytest.raises(ValueError):
        client.set_unit("kelvin")


def test_weather_codes_read_as_words():
    assert describe(0) == "Clear" and describe(63) == "Rain" and describe(95) == "Thunderstorms"
    assert describe(1234) == ""
