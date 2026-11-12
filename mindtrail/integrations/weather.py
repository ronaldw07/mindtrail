"""Today's weather from Open-Meteo (free, no key).

You give a city name once; it's turned into coordinates by Open-Meteo's
geocoder and only the coordinates are used after that. Nothing else about
you is sent. The forecast is cached for CACHE_MINUTES and refreshed in the
background, so Today never waits on it.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
PLACE_KEY = "weather_place"
UNIT_KEY = "weather_unit"
CACHE_KEY = "weather_cache"
CACHE_MINUTES = 60
TIMEOUT_SECONDS = 10

# WMO weather codes, grouped the way a person would say them.
_CODES = (
    ({0}, "Clear"), ({1}, "Mostly clear"), ({2}, "Partly cloudy"), ({3}, "Overcast"),
    ({45, 48}, "Fog"), ({51, 53, 55, 56, 57}, "Drizzle"), ({61, 63, 65, 66, 67}, "Rain"),
    ({71, 73, 75, 77}, "Snow"), ({80, 81, 82}, "Showers"), ({85, 86}, "Snow showers"),
    ({95, 96, 99}, "Thunderstorms"),
)


class WeatherError(RuntimeError):
    pass


def describe(code: int) -> str:
    return next((label for codes, label in _CODES if code in codes), "")


def _get_json(url: str, params: dict) -> dict:
    full = url + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(full, headers={"User-Agent": "mindtrail"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise WeatherError(f"couldn't reach the weather service: {exc}") from exc


class WeatherClient:
    def __init__(self, state, get=_get_json, clock=lambda: datetime.now(timezone.utc)):
        self._state = state
        self._get = get
        self._clock = clock
        self._lock = threading.Lock()

    def place(self) -> dict:
        return self._state.get(PLACE_KEY, {}) or {}

    def unit(self) -> str:
        return "celsius" if self._state.get(UNIT_KEY, "fahrenheit") == "celsius" else "fahrenheit"

    def set_unit(self, unit: str) -> None:
        if unit not in ("fahrenheit", "celsius"):
            raise ValueError("unit must be fahrenheit or celsius")
        self._state.set(UNIT_KEY, unit)
        self._state.set(CACHE_KEY, {})

    def set_city(self, name: str) -> dict:
        """Look a city up and remember its coordinates. "" clears it."""
        name = name.strip()
        if not name:
            self._state.set(PLACE_KEY, {})
            self._state.set(CACHE_KEY, {})
            return {}
        found = (self._get(GEOCODE_URL, {"name": name, "count": 1}).get("results") or [None])[0]
        if not found:
            raise ValueError(f"couldn't find a place called “{name}”")
        place = {"name": ", ".join(p for p in (found.get("name"), found.get("admin1")) if p),
                 "lat": found["latitude"], "lon": found["longitude"]}
        self._state.set(PLACE_KEY, place)
        self._state.set(CACHE_KEY, {})
        return place

    def refresh(self) -> dict:
        place = self.place()
        if not place:
            return {}
        with self._lock:
            try:
                raw = self._get(FORECAST_URL, {
                    "latitude": place["lat"], "longitude": place["lon"],
                    "current": "temperature_2m,weather_code",
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                    "temperature_unit": self.unit(), "timezone": "auto", "forecast_days": 1,
                })
                daily = raw["daily"]
                cache = {
                    "fetched_at": self._clock().isoformat(),
                    "temp": round(raw["current"]["temperature_2m"]),
                    "summary": describe(int(raw["current"]["weather_code"])),
                    "high": round(daily["temperature_2m_max"][0]),
                    "low": round(daily["temperature_2m_min"][0]),
                    "rain": daily["precipitation_probability_max"][0],
                }
            except (WeatherError, KeyError, IndexError, TypeError, ValueError) as exc:
                return {**(self._state.get(CACHE_KEY) or {}), "error": str(exc)}
            self._state.set(CACHE_KEY, cache)
            return cache

    def cached(self) -> dict:
        place = self.place()
        if not place:
            return {"configured": False}
        return {"configured": True, "place": place["name"], "unit": self.unit(),
                **(self._state.get(CACHE_KEY) or {})}

    def stale(self) -> bool:
        try:
            fetched = datetime.fromisoformat((self._state.get(CACHE_KEY) or {})["fetched_at"])
        except (KeyError, ValueError, TypeError):
            return True
        return self._clock() - fetched > timedelta(minutes=CACHE_MINUTES)

    def refresh_in_background_if_stale(self) -> None:
        if self.place() and self.stale() and not self._lock.locked():
            threading.Thread(target=self.refresh, daemon=True, name="weather-refresh").start()
