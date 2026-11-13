"""Weather App: a Flask front end for the OpenWeatherMap API.

Routes:
    GET/POST /        Search form. POST redirects to /<city>.
    GET      /<city>  Current weather plus a 4-day forecast for a city.
    GET      /error   "City not found" page.

Each city lookup makes three calls to OpenWeatherMap, one after another:
geocoding (city name -> lat/lon), current weather, and the 5-day forecast.
See docs/architecture-overview.md and docs/API.md.

Configuration: OWM_API_KEY, read from the environment or a .env file.
"""
import datetime
import logging
import requests
import string
from flask import Flask, render_template, request, redirect, url_for
import os
from dotenv import load_dotenv

# Copy variables from .env (if present) into os.environ. Runs once, at import:
# editing .env needs a server restart, since the reloader only watches .py files.
load_dotenv()

# OpenWeatherMap endpoints (free tier). All three take the key as `appid`.
OWM_ENDPOINT = "https://api.openweathermap.org/data/2.5/weather"
OWM_FORECAST_ENDPOINT = "https://api.openweathermap.org/data/2.5/forecast"
GEOCODING_API_ENDPOINT = "https://api.openweathermap.org/geo/1.0/direct"

# Seconds to wait for OpenWeatherMap (per connect and per read) before giving
# up, so a stalled API can't hang a request or a gunicorn worker indefinitely.
OWM_TIMEOUT = 10

log = logging.getLogger(__name__)

# None if OWM_API_KEY is unset. The app still starts (so the search page
# works), but owm_get() refuses to call the API and every lookup shows the
# "unavailable" page.
api_key = os.getenv("OWM_API_KEY")
# api_key = os.environ.get("OWM_API_KEY")
if not api_key:
    log.warning("OWM_API_KEY is not set; weather lookups will fail. See .env.example.")

# Display labels for each OpenWeatherMap unit system. The API converts the
# numbers; these just tell city.html what to print after them.
UNIT_LABELS = {
    "imperial": {"temp": "ºF", "speed": "mph"},
    "metric": {"temp": "ºC", "speed": "meter/sec"},
}


def load_units(value):
    """Normalize the UNITS setting. Anything but metric/imperial means imperial.

    Unset or empty falls back quietly; an unrecognized value (a typo such as
    "metrc") falls back with a warning so it doesn't go unnoticed.
    """
    units = (value or "").strip().lower()
    if units in UNIT_LABELS:
        return units
    if units:
        log.warning("UNITS=%r is not 'metric' or 'imperial'; using imperial", value)
    return "imperial"


# UNITS from .env or the environment: "imperial" (default, °F and mph) or
# "metric" (°C and m/s).
UNITS = load_units(os.getenv("UNITS"))

app = Flask(__name__)


class WeatherAPIError(Exception):
    """OpenWeatherMap couldn't be used: no key, network error, HTTP error, or a non-JSON reply."""


def owm_get(url, params):
    """GET an OpenWeatherMap endpoint and return the parsed JSON.

    Every failure becomes WeatherAPIError, which the error handler below turns
    into a 503 page instead of a crash:
      - no API key configured (checked first, so no request is sent)
      - network problems (connection refused, DNS, ...)
      - no answer within OWM_TIMEOUT seconds
      - HTTP 4xx/5xx, e.g. 401 invalid key or 429 rate limit
      - a body that isn't JSON (e.g. a proxy or firewall page)
    """
    if not api_key:
        raise WeatherAPIError("OWM_API_KEY is not set")
    try:
        response = requests.get(url, params=params, timeout=OWM_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:  # includes Timeout, HTTPError, JSONDecodeError
        # requests puts the full request URL, ?appid=<key> included, into
        # error messages; redact the key so it never reaches the logs.
        detail = str(exc).replace(api_key, "<redacted>")
        raise WeatherAPIError(f"{url}: {detail}") from exc


@app.errorhandler(WeatherAPIError)
def weather_api_unavailable(exc):
    """Show the error page with a 503 when OpenWeatherMap can't be reached or used."""
    log.warning("OpenWeatherMap request failed: %s", exc)
    message = "Weather data is unavailable right now. Please try again later."
    return render_template("error.html", message=message), 503


@app.route("/", methods=["GET", "POST"])
def home():
    """Show the search form; on submit, redirect to that city's page.

    Post/Redirect/Get: the POST never renders weather itself, so the result
    lands on a bookmarkable URL (/London) and refreshing doesn't re-submit.
    """
    if request.method == "POST":
        # Trim spaces; an empty or whitespace-only search just returns here
        # instead of sending a blank name to the API.
        city = (request.form.get("search") or "").strip()
        if not city:
            return redirect(url_for("home"))
        # url_for percent-encodes the name ("New York" -> /New%20York).
        return redirect(url_for("get_weather", city=city))
    return render_template("index.html")


@app.route("/favicon.ico")
def favicon():
    """Answer the browser's automatic icon request without a city lookup.

    Without this route, /<city> would treat "favicon.ico" as a city and spend
    a geocoding call on every page load. 204 = nothing here, and unlike a 404
    it doesn't log an error in the browser console.
    """
    return "", 204


# Catch-all for any single path segment. Fixed paths (/error, /favicon.ico,
# /static/...) take precedence because Flask matches them before variable ones.
# GET only: the search form posts to "/", and allowing POST here made
# POST /error fall through to this route as a city named "Error".
@app.route("/<city>")
def get_weather(city):
    """Render current weather and a 4-day noon forecast for ``city``.

    Redirects to /error when geocoding finds no match. Any API failure (bad
    key, rate limit, network error) raises WeatherAPIError from owm_get(),
    which weather_api_unavailable() turns into a 503 page.
    """
    # A hand-typed URL such as /%20%20 has no name to look up: back to the form.
    if not city.strip():
        return redirect(url_for("home"))

    # "new haven" -> "New Haven", used both for display and for the API query.
    # capwords also trims and collapses extra spaces.
    city_name = string.capwords(city)
    # Server-local time, not the city's: the date shown can be off by a day
    # for cities in distant time zones.
    today = datetime.datetime.now()
    current_date = today.strftime("%A, %B %d")

    # --- 1. Geocoding: city name -> latitude/longitude ----------------------
    # limit=3 asks for up to three matches, but only the first is used, so
    # "Paris" means whichever Paris OpenWeatherMap ranks first.
    location_params = {
        "q": city_name,
        "appid": api_key,
        "limit": 3,
    }

    location_data = owm_get(GEOCODING_API_ENDPOINT, location_params)

    # No match comes back as an empty list. (API errors never get here:
    # owm_get() raises on any non-2xx status.)
    if not location_data:
        return redirect(url_for("error"))
    else:
        lat = location_data[0]['lat']
        lon = location_data[0]['lon']

    # --- 2. Current weather ---------------------------------------------------
    # Shared by both weather calls. UNITS decides what the API returns
    # (imperial: °F and miles/hour; metric: °C and metres/second).
    weather_params = {
        "lat": lat,
        "lon": lon,
        "appid": api_key,
        "units": UNITS,
    }
    weather_data = owm_get(OWM_ENDPOINT, weather_params)

    current_temp = round(weather_data['main']['temp'])
    # Condition group such as "Clear" or "Rain". The templates lowercase it to
    # pick static/assets/<condition>.png.
    current_weather = weather_data['weather'][0]['main']
    # Min/max of the *current* reading across the city area, not the day's
    # low/high (that's one of the exercise's bonus challenges).
    min_temp = round(weather_data['main']['temp_min'])
    max_temp = round(weather_data['main']['temp_max'])
    wind_speed = weather_data['wind']['speed']

    # --- 3. Five-day forecast (one entry every 3 hours) -----------------------
    forecast_data = owm_get(OWM_FORECAST_ENDPOINT, weather_params)

    # Noon forecast for the next four days. Derive the day label from each entry's own
    # date so labels and data can't drift apart (today's noon entry is absent after 12:00 UTC).
    # Note: dt_txt is in UTC, so "12:00:00" is noon UTC, not noon in the city.
    today_str = today.strftime("%Y-%m-%d")
    forecast = [
        {
            "day": datetime.datetime.strptime(item["dt_txt"], "%Y-%m-%d %H:%M:%S").strftime("%a"),
            "temp": round(item["main"]["temp"]),
            "weather": item["weather"][0]["main"],
        }
        for item in forecast_data["list"]
        if item["dt_txt"].endswith("12:00:00") and not item["dt_txt"].startswith(today_str)
    ][:4]

    # today_label heads the first forecast column, which reuses current conditions.
    return render_template("city.html", city_name=city_name, current_date=current_date, current_temp=current_temp,
                           current_weather=current_weather, min_temp=min_temp, max_temp=max_temp, wind_speed=wind_speed,
                           today_label=today.strftime("%a"), forecast=forecast, units=UNIT_LABELS[UNITS])


@app.route("/error")
def error():
    """Show the "city does not exist" page (target of the no-match redirect)."""
    return render_template("error.html")


if __name__ == "__main__":
    # Local development only (`python main.py`). Production uses the Procfile:
    # `gunicorn main:app`, which never runs this block.
    # FLASK_RUN_PORT is the same setting `flask run` reads from .env, so both
    # ways of starting the dev server use the same port.
    app.run(debug=True, port=int(os.getenv("FLASK_RUN_PORT", "5000")))
