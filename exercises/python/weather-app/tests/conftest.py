"""Shared fixtures: a Flask test client and a fake OpenWeatherMap API.

Every test runs against FakeOWM, so no test touches the network or needs a
real OWM_API_KEY. Each test can swap in a different response for any of the
three endpoints, e.g. ``owm.geocode = FakeResponse(401, {...})``.
"""
import datetime

import pytest
import requests

import main


class FakeResponse:
    """The parts of requests.Response that main.py uses."""

    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        # An exception as payload simulates a body that isn't JSON.
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


def geocode_payload(name="London", lat=51.5073, lon=-0.1276):
    return [{"name": name, "lat": lat, "lon": lon, "country": "GB"}]


# The tests' frozen clock: Friday 13 Nov 2026, 20:00 UTC. The `clock` fixture
# makes main.utc_now() return this, so dates never depend on the real time.
FIXED_NOW = datetime.datetime(2026, 11, 13, 20, 0, tzinfo=datetime.timezone.utc)

# City UTC offsets (seconds) used in tests, and what FIXED_NOW is there:
TZ_UTC = 0                 # Fri 13 Nov, 20:00
TZ_NEW_HAVEN = -5 * 3600   # Fri 13 Nov, 15:00
TZ_TOKYO = 9 * 3600        # Sat 14 Nov, 05:00
TZ_MOSCOW = 3 * 3600       # Fri 13 Nov, 23:00 (no forecast readings left today)


def current_payload(temp=3.4, weather="Clear", temp_min=1.2, temp_max=4.6, wind=0.79, tz=TZ_UTC):
    return {
        "dt": int(FIXED_NOW.timestamp()),
        "timezone": tz,
        "main": {"temp": temp, "temp_min": temp_min, "temp_max": temp_max},
        "weather": [{"main": weather}],
        "wind": {"speed": wind},
    }


def forecast_payload(tz=TZ_UTC, count=40):
    """``count`` readings every 3 hours from the first slot after FIXED_NOW,
    like the real API (40 readings = 5 days).

    Values are chosen so tests can predict exactly what the app shows. For a
    reading at local time L, on local day N (0 = the city's today):
      temp      = 10*N + L.hour/3   -> each day's readings are distinct
      temp_min  = temp - 1,  temp_max = temp + 1
      weather   = "Rain" on odd days, "Clouds" on even days, for the reading
                  within 90 minutes of local noon; "Snow" for all others
    So with whole-hour offsets, day N's low is 10*N - 1 + (earliest hour)/3
    and its high is 10*N + 1 + (latest hour)/3.
    """
    city_tz = datetime.timezone(datetime.timedelta(seconds=tz))
    local_today = FIXED_NOW.astimezone(city_tz).date()
    first = FIXED_NOW.replace(minute=0) + datetime.timedelta(hours=3 - FIXED_NOW.hour % 3)
    entries = []
    for i in range(count):
        utc = first + datetime.timedelta(hours=3 * i)
        local = utc.astimezone(city_tz)
        n = (local.date() - local_today).days
        temp = 10 * n + local.hour / 3
        near_noon = abs(local.hour * 60 + local.minute - 720) <= 90
        entries.append({
            "dt": int(utc.timestamp()),
            "dt_txt": utc.strftime("%Y-%m-%d %H:%M:%S"),
            "main": {"temp": temp, "temp_min": temp - 1, "temp_max": temp + 1},
            "weather": [{"main": ("Clouds", "Rain")[n % 2] if near_noon else "Snow"}],
        })
    return {"city": {"timezone": tz}, "list": entries}


def set_city_timezone(owm, tz):
    """Point both weather responses at a city with UTC offset ``tz``."""
    owm.current = FakeResponse(200, current_payload(tz=tz))
    owm.forecast = FakeResponse(200, forecast_payload(tz=tz))


class FakeOWM:
    """Stands in for requests.get and routes each call by URL."""

    def __init__(self):
        self.geocode = FakeResponse(200, geocode_payload())
        self.current = FakeResponse(200, current_payload())
        self.forecast = FakeResponse(200, forecast_payload())
        self.calls = []

    def __call__(self, url, params=None, **kwargs):
        self.calls.append({"url": url, "params": params, "kwargs": kwargs})
        routes = {
            main.GEOCODING_API_ENDPOINT: "geocode",
            main.OWM_ENDPOINT: "current",
            main.OWM_FORECAST_ENDPOINT: "forecast",
        }
        if url not in routes:
            raise AssertionError(f"unexpected HTTP call to {url}")
        response = getattr(self, routes[url])
        if isinstance(response, Exception):
            raise response
        return response

    def calls_to(self, url):
        return [c for c in self.calls if c["url"] == url]


@pytest.fixture(autouse=True)
def owm(monkeypatch):
    """Replace requests.get in main.py for every test (autouse: no real calls)."""
    fake = FakeOWM()
    monkeypatch.setattr(main.requests, "get", fake)
    monkeypatch.setattr(main, "api_key", "test-key")
    # Pin units so a UNITS line in your .env can't change test results.
    monkeypatch.setattr(main, "UNITS", "imperial")
    # Freeze the clock (see FIXED_NOW).
    monkeypatch.setattr(main, "utc_now", lambda: FIXED_NOW)
    return fake


@pytest.fixture
def client():
    main.app.config["TESTING"] = True
    with main.app.test_client() as client:
        yield client
