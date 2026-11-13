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
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


def geocode_payload(name="London", lat=51.5073, lon=-0.1276):
    return [{"name": name, "lat": lat, "lon": lon, "country": "GB"}]


def current_payload(temp=3.4, weather="Clear", temp_min=1.2, temp_max=4.6, wind=0.79):
    return {
        "main": {"temp": temp, "temp_min": temp_min, "temp_max": temp_max},
        "weather": [{"main": weather}],
        "wind": {"speed": wind},
    }


def forecast_payload(days=6):
    """Forecast entries every 3 hours, starting at 00:00 today, for ``days`` days.

    The noon temperature on day offset N is 10 + N, and the weather alternates
    Clouds/Rain, so tests can tell exactly which entries the app picked.
    """
    start = datetime.datetime.combine(datetime.date.today(), datetime.time(0))
    entries = []
    for i in range(days * 8):
        ts = start + datetime.timedelta(hours=3 * i)
        offset = (ts.date() - start.date()).days
        noon = ts.hour == 12
        entries.append({
            "dt_txt": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "main": {"temp": 10 + offset if noon else -50},
            "weather": [{"main": ("Clouds", "Rain")[offset % 2] if noon else "Snow"}],
        })
    return {"list": entries}


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
    return fake


@pytest.fixture
def client():
    main.app.config["TESTING"] = True
    with main.app.test_client() as client:
        yield client
