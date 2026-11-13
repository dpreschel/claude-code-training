"""Unit tests for main.py, run against the fake OpenWeatherMap in conftest.py.

Tests marked xfail document known bugs (see the Task 1 review). They are
strict: once a fix lands, the test passes, pytest reports XPASS as a failure,
and that's the cue to delete the marker.
"""
import datetime

import pytest
import requests

import main
from conftest import FakeResponse, forecast_payload, geocode_payload


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

    def test_whitespace_search_returns_home(self, client, owm):
        response = client.post("/", data={"search": "   "})
        assert response.headers["Location"] == "/"
        assert owm.calls == []

    def test_search_trims_surrounding_spaces(self, client):
        response = client.post("/", data={"search": "  London  "})
        assert response.headers["Location"] == "/London"

    def test_whitespace_city_url_returns_home(self, client, owm):
        response = client.get("/%20%20%20")
        assert response.status_code == 302
        assert response.headers["Location"] == "/"
        assert owm.calls == []


# --- City weather page: happy path --------------------------------------------

class TestCityPage:
    def test_renders_current_weather(self, client):
        response = client.get("/London")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "<h1> London </h1>" in html
        assert "3ºF" in html                     # 3.4 rounded
        assert "Clear" in html
        assert "1° - 5°" in html                 # temp_min 1.2, temp_max 4.6, rounded
        assert "0.79 mph" in html

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

    @pytest.mark.parametrize("typed", ["New Haven", "new Haven"])
    def test_new_haven_search(self, client, owm, typed):
        owm.geocode = FakeResponse(200, geocode_payload("New Haven", lat=41.3083, lon=-72.9279))

        response = client.post("/", data={"search": typed}, follow_redirects=True)

        assert response.status_code == 200
        assert "<h1> New Haven </h1>" in response.get_data(as_text=True)
        geocode_call, current_call, forecast_call = owm.calls
        assert geocode_call["params"]["q"] == "New Haven"
        for call in (current_call, forecast_call):
            assert (call["params"]["lat"], call["params"]["lon"]) == (41.3083, -72.9279)

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
            assert call["params"]["units"] == "imperial"


# --- UNITS setting -------------------------------------------------------------

class TestUnits:
    def test_imperial_labels_by_default(self, client, owm):
        html = client.get("/London").get_data(as_text=True)
        assert "3ºF" in html
        assert "0.79 mph" in html
        assert {c["params"]["units"] for c in owm.calls[1:]} == {"imperial"}

    def test_metric_changes_api_units_and_labels(self, client, owm, monkeypatch):
        monkeypatch.setattr(main, "UNITS", "metric")
        html = client.get("/London").get_data(as_text=True)
        assert "3ºC" in html
        assert "0.79 meter/sec" in html
        assert "ºF" not in html and " mph" not in html
        assert {c["params"]["units"] for c in owm.calls[1:]} == {"metric"}

    @pytest.mark.parametrize("raw, expected", [
        (None, "imperial"),          # UNITS not set
        ("", "imperial"),
        ("metric", "metric"),
        ("  Metric ", "metric"),     # case and whitespace forgiven
        ("IMPERIAL", "imperial"),
    ])
    def test_load_units_accepts(self, raw, expected):
        assert main.load_units(raw) == expected

    @pytest.mark.parametrize("raw", ["xxx", "celsius", "standard", "metrc"])
    def test_unrecognized_units_fall_back_to_imperial_with_warning(self, raw, caplog):
        assert main.load_units(raw) == "imperial"
        assert "using imperial" in caplog.text

    def test_unset_units_fall_back_quietly(self, caplog):
        assert main.load_units(None) == "imperial"
        assert caplog.text == ""


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

    # --- OpenWeatherMap failures: 503 "unavailable" page, never a crash ---------

    def assert_unavailable(self, response):
        assert response.status_code == 503
        assert b"Weather data is unavailable" in response.data
        assert b"This city does not exist" not in response.data

    def test_geocoding_api_error_shows_unavailable_page(self, client, owm):
        owm.geocode = FakeResponse(401, {"cod": 401, "message": "Invalid API key"})
        self.assert_unavailable(client.get("/London"))
        assert len(owm.calls) == 1                # stops at the failed call

    def test_current_weather_api_error_shows_unavailable_page(self, client, owm):
        owm.current = FakeResponse(500, {"cod": 500, "message": "Internal error"})
        self.assert_unavailable(client.get("/London"))
        assert len(owm.calls) == 2

    def test_forecast_api_error_shows_unavailable_page(self, client, owm):
        owm.forecast = FakeResponse(429, {"cod": 429, "message": "Rate limit exceeded"})
        self.assert_unavailable(client.get("/London"))

    def test_network_failure_shows_unavailable_page(self, client, owm):
        owm.geocode = requests.ConnectionError("network down")
        self.assert_unavailable(client.get("/London"))

    def test_timeout_shows_unavailable_page(self, client, owm):
        owm.current = requests.Timeout("read timed out")
        self.assert_unavailable(client.get("/London"))

    def test_non_json_reply_shows_unavailable_page(self, client, owm):
        """E.g. a proxy or firewall answering with an HTML/text page."""
        owm.geocode = FakeResponse(200, requests.JSONDecodeError("Expecting value", "Blocked", 0))
        self.assert_unavailable(client.get("/London"))

    def test_every_api_call_has_a_timeout(self, client, owm):
        client.get("/London")
        assert [c["kwargs"].get("timeout") for c in owm.calls] == [main.OWM_TIMEOUT] * 3

    def test_missing_api_key_shows_unavailable_without_calling_api(self, client, owm, monkeypatch):
        monkeypatch.setattr(main, "api_key", None)
        self.assert_unavailable(client.get("/London"))
        assert owm.calls == []

    def test_api_failure_is_logged(self, client, owm, caplog):
        owm.geocode = FakeResponse(401, {"cod": 401, "message": "Invalid API key"})
        client.get("/London")
        assert "OpenWeatherMap request failed" in caplog.text

    def test_api_key_is_redacted_from_logs(self, client, owm, caplog):
        # requests' real HTTPError message includes the URL with ?appid=<key>.
        owm.geocode = requests.HTTPError(
            "401 Client Error: Unauthorized for url: "
            "https://api.openweathermap.org/geo/1.0/direct?q=London&appid=test-key&limit=3")
        client.get("/London")
        assert "test-key" not in caplog.text
        assert "appid=<redacted>" in caplog.text

    def test_favicon_does_not_call_api(self, client, owm):
        response = client.get("/favicon.ico")
        assert response.status_code == 204
        assert owm.calls == []

    @pytest.mark.parametrize("path", ["/error", "/London"])
    def test_post_to_city_or_error_is_not_allowed(self, client, owm, path):
        """POST /error used to fall through to /<city> as a city named "Error"."""
        response = client.post(path)
        assert response.status_code == 405
        assert owm.calls == []
