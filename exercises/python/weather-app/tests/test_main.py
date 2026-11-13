"""Unit tests for main.py, run against the fake OpenWeatherMap in conftest.py.

Tests marked xfail document known bugs (see the Task 1 review). They are
strict: once a fix lands, the test passes, pytest reports XPASS as a failure,
and that's the cue to delete the marker.
"""
import datetime
import pathlib

import pytest
import requests

import main
from conftest import (FakeResponse, TZ_MOSCOW, TZ_NEW_HAVEN, TZ_TOKYO, current_payload,
                      forecast_payload, geocode_payload, set_city_timezone)


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
        # Today's low/high: current 1.2-4.6 plus tonight's 21:00 reading (6-8).
        assert "1° - 8°" in html
        assert "0.79 mph" in html

    def test_shows_todays_date_and_weekday(self, client):
        html = client.get("/London").get_data(as_text=True)   # clock: Fri 13 Nov, 20:00 UTC
        assert "Friday, November 13" in html
        assert "<p> Fri </p>" in html

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


# --- Forecast: city-local days, daily low/high (bugs 8, 9) -----------------------
# Expected values follow from forecast_payload() in conftest.py: day N's readings
# run 10*N + hour/3, +/-1 for min/max, so a full day (hours 0-21) has
# low 10*N - 1 and high 10*N + 8.

class TestForecast:
    def _context(self, client, monkeypatch, path="/London"):
        """Return the variables passed to city.html."""
        captured = {}

        def fake_render(template, **context):
            captured.update(context)
            return ""

        monkeypatch.setattr(main, "render_template", fake_render)
        client.get(path)
        return captured

    def test_next_four_days_with_daily_high_and_low(self, client, monkeypatch):
        days = self._context(client, monkeypatch)["forecast"]
        assert [d["day"] for d in days] == ["Sat", "Sun", "Mon", "Tue"]
        assert [d["low"] for d in days] == [9, 19, 29, 39]
        assert [d["high"] for d in days] == [18, 28, 38, 48]

    def test_condition_comes_from_reading_nearest_local_noon(self, client, monkeypatch):
        days = self._context(client, monkeypatch)["forecast"]
        assert [d["weather"] for d in days] == ["Rain", "Clouds", "Rain", "Clouds"]
        assert [d["icon"] for d in days] == ["rain", "clouds", "rain", "clouds"]

    def test_page_shows_high_then_low(self, client):
        html = client.get("/London").get_data(as_text=True)
        assert '18º <span class="forecast-low">9º</span>' in html

    def test_tokyo_uses_its_own_date(self, client, owm, monkeypatch):
        """20:00 UTC Friday is already 05:00 Saturday in Tokyo (bug 8)."""
        set_city_timezone(owm, TZ_TOKYO)
        context = self._context(client, monkeypatch, "/Tokyo")
        assert context["current_date"] == "Saturday, November 14"
        assert context["today_label"] == "Sat"
        assert [d["day"] for d in context["forecast"]] == ["Sun", "Mon", "Tue", "Wed"]

    def test_new_haven_groups_readings_by_local_day(self, client, owm, monkeypatch):
        """Grouping by UTC date would pull Friday-evening readings into Saturday."""
        set_city_timezone(owm, TZ_NEW_HAVEN)
        days = self._context(client, monkeypatch, "/New Haven")["forecast"]
        assert [d["day"] for d in days] == ["Sat", "Sun", "Mon", "Tue"]
        assert [d["low"] for d in days] == [9, 19, 29, 39]
        assert [d["high"] for d in days] == [18, 28, 38, 48]
        # Local readings fall at 1, 4, 7, 10, 13 ...; 13:00 is closest to noon.
        assert [d["weather"] for d in days] == ["Rain", "Clouds", "Rain", "Clouds"]

    def test_today_low_high_includes_rest_of_today(self, client, owm, monkeypatch):
        # Tokyo, 05:00: readings 06:00-21:00 remain today (temps 2-7, so 1-8).
        set_city_timezone(owm, TZ_TOKYO)
        context = self._context(client, monkeypatch, "/Tokyo")
        assert (context["min_temp"], context["max_temp"]) == (1, 8)

    def test_today_low_can_come_from_later_today(self, client, owm, monkeypatch):
        # Warm now (9.6-10.4) but colder later today (Tokyo readings 1-8).
        set_city_timezone(owm, TZ_TOKYO)
        owm.current = FakeResponse(200, current_payload(temp=10, temp_min=9.6, temp_max=10.4, tz=TZ_TOKYO))
        context = self._context(client, monkeypatch, "/Tokyo")
        assert (context["min_temp"], context["max_temp"]) == (1, 10)

    def test_today_low_high_late_at_night_uses_current_reading(self, client, owm, monkeypatch):
        # Moscow, 23:00: the next reading is tomorrow, so only the current
        # reading (1.2-4.6) counts for today.
        set_city_timezone(owm, TZ_MOSCOW)
        context = self._context(client, monkeypatch, "/Moscow")
        assert (context["min_temp"], context["max_temp"]) == (1, 5)
        assert context["forecast"][0]["day"] == "Sat"

    def test_short_forecast_shows_fewer_days(self, client, owm, monkeypatch):
        owm.forecast = FakeResponse(200, forecast_payload(count=16))   # through Sunday
        days = self._context(client, monkeypatch)["forecast"]
        assert [d["day"] for d in days] == ["Sat", "Sun"]

    def test_city_time_converts_utc_to_local(self):
        ts = datetime.datetime(2026, 11, 13, 20, 0, tzinfo=datetime.timezone.utc).timestamp()
        assert main.city_time(ts, TZ_TOKYO).strftime("%a %H:%M") == "Sat 05:00"
        assert main.city_time(ts, TZ_NEW_HAVEN).strftime("%a %H:%M") == "Fri 15:00"
        assert main.city_time(ts, 5 * 3600 + 1800).strftime("%H:%M") == "01:30"   # India, +5:30


# --- Icons (bug 12) ------------------------------------------------------------

class TestIcons:
    @pytest.mark.parametrize("condition, icon", [
        ("Rain", "rain"), ("Clear", "clear"), ("Thunderstorm", "thunderstorm"),
        ("Dust", "haze"), ("Sand", "haze"), ("Ash", "smoke"), ("Squall", "wind"),
        ("Volcano", "clouds"), ("", "clouds"), (None, "clouds"),
    ])
    def test_icon_for(self, condition, icon):
        assert main.icon_for(condition) == icon

    @pytest.mark.parametrize("condition", [
        "Thunderstorm", "Drizzle", "Rain", "Snow", "Mist", "Smoke", "Haze", "Dust",
        "Fog", "Sand", "Ash", "Squall", "Tornado", "Clear", "Clouds",
    ])
    def test_every_owm_condition_has_an_icon_file(self, condition):
        """All 15 OpenWeatherMap condition groups map to a file that exists."""
        path = pathlib.Path(main.app.static_folder) / "assets" / f"{main.icon_for(condition)}.png"
        assert path.is_file(), path

    def test_page_uses_mapped_icon(self, client, owm):
        owm.current = FakeResponse(200, current_payload(weather="Dust"))
        html = client.get("/London").get_data(as_text=True)
        assert "/static/assets/haze.png" in html
        assert "dust.png" not in html
        assert "Dust" in html                    # the condition name is still shown


# --- FLASK_RUN_PORT (bug 13) -----------------------------------------------------

class TestPort:
    @pytest.mark.parametrize("raw, expected", [
        (None, 5000), ("", 5000), ("5001", 5001), (" 8080 ", 8080), ("65535", 65535),
    ])
    def test_load_port_accepts(self, raw, expected):
        assert main.load_port(raw) == expected

    @pytest.mark.parametrize("raw", ["abc", "50.5", "0", "-1", "70000"])
    def test_bad_port_falls_back_to_5000_with_warning(self, raw, caplog):
        assert main.load_port(raw) == 5000
        assert "is not a port number" in caplog.text


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
