"""Unit tests for main.py, run against the fake OpenWeatherMap in conftest.py.

Tests marked xfail document known bugs (see the Task 1 review). They are
strict: once a fix lands, the test passes, pytest reports XPASS as a failure,
and that's the cue to delete the marker.
"""
import datetime

import pytest
import requests

import main
from conftest import FakeResponse, forecast_payload


def known_bug(reason):
    return pytest.mark.xfail(reason=reason, strict=True)


# --- Home page and search form -------------------------------------------------

class TestHome:
    def test_get_shows_search_form(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert b'name="search"' in response.data

    def test_home_makes_no_api_calls(self, client, owm):
        client.get("/")
        assert owm.calls == []

    def test_search_redirects_to_city_page(self, client):
        response = client.post("/", data={"search": "London"})
        assert response.status_code == 302
        assert response.headers["Location"] == "/London"

    def test_search_url_encodes_city(self, client):
        response = client.post("/", data={"search": "New York"})
        assert response.headers["Location"] == "/New%20York"

    def test_empty_search_returns_home(self, client, owm):
        response = client.post("/", data={"search": ""})
        assert response.headers["Location"] == "/"
        assert owm.calls == []

    @known_bug("whitespace-only search is passed to the API and ends in a 500")
    def test_whitespace_search_returns_home(self, client):
        response = client.post("/", data={"search": "   "})
        assert response.headers["Location"] == "/"


# --- City weather page: happy path --------------------------------------------

class TestCityPage:
    def test_renders_current_weather(self, client):
        response = client.get("/London")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "<h1> London </h1>" in html
        assert "3ºC" in html                     # 3.4 rounded
        assert "Clear" in html
        assert "1° - 5°" in html                 # temp_min 1.2, temp_max 4.6, rounded
        assert "0.79 meter/sec" in html

    def test_shows_todays_date_and_weekday(self, client):
        html = client.get("/London").get_data(as_text=True)
        today = datetime.datetime.now()
        assert today.strftime("%A, %B %d") in html
        assert f"<p> {today.strftime('%a')} </p>" in html

    def test_weather_icon_uses_lowercase_condition(self, client):
        html = client.get("/London").get_data(as_text=True)
        assert "/static/assets/clear.png" in html

    def test_city_name_is_title_cased(self, client, owm):
        html = client.get("/new york").get_data(as_text=True)
        assert "<h1> New York </h1>" in html
        assert owm.calls_to(main.GEOCODING_API_ENDPOINT)[0]["params"]["q"] == "New York"

    def test_makes_exactly_three_api_calls_in_order(self, client, owm):
        client.get("/London")
        assert [c["url"] for c in owm.calls] == [
            main.GEOCODING_API_ENDPOINT,
            main.OWM_ENDPOINT,
            main.OWM_FORECAST_ENDPOINT,
        ]

    def test_api_key_sent_on_every_call(self, client, owm):
        client.get("/London")
        assert [c["params"]["appid"] for c in owm.calls] == ["test-key"] * 3

    def test_all_endpoints_use_https(self):
        for url in (main.GEOCODING_API_ENDPOINT, main.OWM_ENDPOINT, main.OWM_FORECAST_ENDPOINT):
            assert url.startswith("https://"), url

    def test_uses_first_geocoding_match_for_weather_calls(self, client, owm):
        owm.geocode = FakeResponse(200, [
            {"lat": 1.0, "lon": 2.0},
            {"lat": 9.0, "lon": 9.0},
        ])
        client.get("/Springfield")
        for call in owm.calls[1:]:
            assert (call["params"]["lat"], call["params"]["lon"]) == (1.0, 2.0)
            assert call["params"]["units"] == "metric"


# --- Forecast selection ----------------------------------------------------------

class TestForecast:
    def _forecast_days(self, client):
        """Return the forecast list exactly as passed to the template."""
        captured = {}

        def fake_render(template, **context):
            captured.update(context)
            return ""

        original = main.render_template
        main.render_template = fake_render
        try:
            client.get("/London")
        finally:
            main.render_template = original
        return captured["forecast"]

    def test_shows_next_four_days_at_noon_excluding_today(self, client):
        days = self._forecast_days(client)
        today = datetime.date.today()
        expected_labels = [(today + datetime.timedelta(days=n)).strftime("%a") for n in range(1, 5)]
        assert [d["day"] for d in days] == expected_labels
        assert [d["temp"] for d in days] == [11, 12, 13, 14]   # noon temps, not -50
        assert [d["weather"] for d in days] == ["Rain", "Clouds", "Rain", "Clouds"]

    def test_afternoon_request_without_todays_noon_entry(self, client, owm):
        """After 12:00 UTC the API no longer returns today's noon slot."""
        payload = forecast_payload()
        today = datetime.date.today().strftime("%Y-%m-%d")
        payload["list"] = [e for e in payload["list"] if not e["dt_txt"].startswith(today)]
        owm.forecast = FakeResponse(200, payload)
        assert [d["temp"] for d in self._forecast_days(client)] == [11, 12, 13, 14]

    def test_short_forecast_shows_fewer_days(self, client, owm):
        owm.forecast = FakeResponse(200, forecast_payload(days=3))
        assert [d["temp"] for d in self._forecast_days(client)] == [11, 12]


# --- Error handling ----------------------------------------------------------------

class TestErrors:
    def test_unknown_city_redirects_to_error_page(self, client, owm):
        owm.geocode = FakeResponse(200, [])
        response = client.get("/Xyzzyville")
        assert response.status_code == 302
        assert response.headers["Location"] == "/error"
        assert len(owm.calls) == 1                # stops after geocoding

    def test_error_page(self, client):
        response = client.get("/error")
        assert response.status_code == 200
        assert b"This city does not exist" in response.data

    @known_bug("geocoding error JSON (e.g. 401 invalid key) is indexed like a list: KeyError")
    def test_geocoding_api_error_shows_error_page(self, client, owm):
        owm.geocode = FakeResponse(401, {"cod": 401, "message": "Invalid API key"})
        response = client.get("/London")
        assert response.status_code in (302, 503)

    @known_bug("raise_for_status() on the current-weather call is never caught")
    def test_current_weather_api_error_shows_error_page(self, client, owm):
        owm.current = FakeResponse(500, {"cod": 500, "message": "Internal error"})
        response = client.get("/London")
        assert response.status_code in (302, 503)

    @known_bug("forecast response is never checked: KeyError 'list'")
    def test_forecast_api_error_shows_error_page(self, client, owm):
        owm.forecast = FakeResponse(429, {"cod": 429, "message": "Rate limit exceeded"})
        response = client.get("/London")
        assert response.status_code in (302, 503)

    @known_bug("network failures are not caught")
    def test_network_failure_shows_error_page(self, client, owm):
        owm.geocode = requests.ConnectionError("network down")
        response = client.get("/London")
        assert response.status_code in (302, 503)

    @known_bug("requests.get is called without a timeout")
    def test_every_api_call_has_a_timeout(self, client, owm):
        client.get("/London")
        assert all(c["kwargs"].get("timeout") for c in owm.calls)

    @known_bug("missing OWM_API_KEY is not detected; the API returns 401 and the app crashes")
    def test_missing_api_key_shows_error_without_calling_api(self, client, owm, monkeypatch):
        monkeypatch.setattr(main, "api_key", None)
        owm.geocode = FakeResponse(401, {"cod": 401, "message": "Invalid API key"})
        response = client.get("/London")
        assert response.status_code in (302, 503)
        assert owm.calls == []

    @known_bug("the browser's /favicon.ico request is treated as a city lookup")
    def test_favicon_does_not_call_api(self, client, owm):
        client.get("/favicon.ico")
        assert owm.calls == []
