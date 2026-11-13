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

# None if OWM_API_KEY is unset. Nothing checks this: a missing key surfaces
# later as a 401 from the API (see docs/TROUBLESHOOTING.md).
api_key = os.getenv("OWM_API_KEY")
# api_key = os.environ.get("OWM_API_KEY")

app = Flask(__name__)


@app.route("/", methods=["GET", "POST"])
def home():
    """Show the search form; on submit, redirect to that city's page.

    Post/Redirect/Get: the POST never renders weather itself, so the result
    lands on a bookmarkable URL (/London) and refreshing doesn't re-submit.
    """
    if request.method == "POST":
        city = request.form.get("search")
        # url_for percent-encodes the name ("New York" -> /New%20York).
        # An empty search builds "/" and simply returns to this page.
        return redirect(url_for("get_weather", city=city))
    return render_template("index.html")


# Catch-all for any single path segment, so /favicon.ico or /robots.txt is
# also treated as a city name. /error and /static/... take precedence because
# Flask matches fixed paths before variable ones.
@app.route("/<city>", methods=["GET", "POST"])
def get_weather(city):
    """Render current weather and a 4-day noon forecast for ``city``.

    Redirects to /error when geocoding finds no match. Other API failures
    (bad key, rate limit, network errors) are not handled and produce a 500.
    """
    # "new haven" -> "New Haven", used both for display and for the API query.
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

    location_response = requests.get(GEOCODING_API_ENDPOINT, params=location_params)
    location_data = location_response.json()

    # No match comes back as an empty list. An API *error* comes back as a
    # non-empty dict (e.g. {"cod": 401, ...}), which passes this check and then
    # fails on location_data[0] with KeyError: 0.
    if not location_data:
        return redirect(url_for("error"))
    else:
        lat = location_data[0]['lat']
        lon = location_data[0]['lon']

    # --- 2. Current weather ---------------------------------------------------
    # Shared by both weather calls. units=metric gives °C and metres/second.
    weather_params = {
        "lat": lat,
        "lon": lon,
        "appid": api_key,
        "units": "metric",
    }
    weather_response = requests.get(OWM_ENDPOINT, weather_params)
    # Raises HTTPError on 4xx/5xx; nothing catches it, so Flask returns a 500.
    weather_response.raise_for_status()
    weather_data = weather_response.json()

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
    # Unlike the call above, the status isn't checked: an error response
    # fails below with KeyError: 'list'.
    forecast_response = requests.get(OWM_FORECAST_ENDPOINT, weather_params)
    forecast_data = forecast_response.json()

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
                           today_label=today.strftime("%a"), forecast=forecast)


@app.route("/error")
def error():
    """Show the "city does not exist" page (target of the no-match redirect)."""
    return render_template("error.html")


if __name__ == "__main__":
    # Local development only (`python main.py`). Production uses the Procfile:
    # `gunicorn main:app`, which never runs this block.
    app.run(debug=True)
