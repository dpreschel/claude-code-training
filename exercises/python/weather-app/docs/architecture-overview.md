# Architecture Overview

How the Weather App is put together, why, and where it's headed. For
diagrams (component map, request sequence, `get_weather()` flowchart), see
[architecture.md](architecture.md).

## At a glance

- **Style:** a server-rendered Flask app with no database and no JavaScript.
- **Size:** one Python module (`main.py`), three routes, three templates.
- **State:** none. Each request is independent; nothing is cached or stored.
- **External dependency:** the OpenWeatherMap API. Every city page makes three
  calls to it, one after another.

```
Browser ──HTTP──▶ Flask (main.py) ──HTTPS──▶ OpenWeatherMap
   ▲                  │                       (geocoding, current, forecast)
   └──── HTML ◀── Jinja2 templates + static CSS/icons
```

## Components

| Component | Files | Responsibility |
|---|---|---|
| **Configuration** | `main.py` (top), `.env` | Loads `OWM_API_KEY` with python-dotenv; defines the three endpoint URLs |
| **Routes** | `main.py`: `home()`, `get_weather()`, `error()` | HTTP handling, redirects, choosing a template |
| **API access** | inline in `get_weather()` | Builds parameters, calls `requests.get`, reads the JSON |
| **Data shaping** | inline in `get_weather()` | Rounding, picking fields, selecting the noon forecast entries |
| **Presentation** | `templates/*.html`, `static/` | Jinja2 pages, CSS layout, one icon per weather condition |
| **Tests** | `tests/` | Flask test client + FakeOWM (a fake `requests.get`) |
| **Deployment** | `Procfile` | `gunicorn main:app` |

## Request lifecycle

A search for "new haven", end to end:

1. **`POST /`** with `search=new haven`. `home()` redirects to
   `/new%20haven` (Post/Redirect/Get).
2. **`GET /new%20haven`**. Flask's URL map matches `/<city>` and calls
   `get_weather("new haven")`.
3. **Normalize:** `capwords` → `"New Haven"`; read today's date from the
   server's clock.
4. **Geocode:** `GET /geo/1.0/direct?q=New Haven&limit=3`. An empty list
   redirects to `/error`. Otherwise the first match gives `lat`, `lon`.
5. **Current weather:** `GET /data/2.5/weather?lat&lon&units=metric`.
   `raise_for_status()`, then pick temperature, condition, min/max, wind.
6. **Forecast:** `GET /data/2.5/forecast?lat&lon&units=metric` returns 40
   entries (every 3 hours for 5 days). Keep entries timestamped `12:00:00`
   whose date isn't today, then take the first 4.
7. **Render** `city.html` with nine template variables. The browser then loads
   `main.css` and the icons from `/static`.

Typical cost: **three outbound HTTPS requests per page view**, one after
another, so the page takes about as long as all three combined.

## Dependencies

```
main.py
 ├── flask ──────── werkzeug (routing, WSGI, dev server)
 │                └ jinja2 ── markupsafe (templates, HTML escaping)
 ├── requests ───── urllib3, certifi, idna, charset-normalizer
 ├── python-dotenv
 └── stdlib: datetime, string, os

gunicorn (production server only, via Procfile)
pytest (tests only, requirements-dev.txt)
```

`requirements.txt` uses compatible-release pins (`~=`), so patch versions can
change between installs. There is no lock file.

## Design decisions

| Decision | Why | Trade-off |
|---|---|---|
| **Server-side rendering, no JS** | Simple; works everywhere; the API key never reaches the browser | Every search is a full page load |
| **Post/Redirect/Get** for search | City pages get clean, bookmarkable URLs; refresh doesn't re-submit | One extra round trip |
| **City name in the URL** (`/<city>`) | Shareable links | A catch-all route that also captures `/favicon.ico` and `POST /error` |
| **Geocode first, then query by lat/lon** | OpenWeatherMap's recommended approach (querying weather by city name is deprecated) | Three API calls instead of two |
| **Noon reading as the "day" forecast** | One value per day from the 3-hourly feed, cheaply | Noon UTC isn't noon locally; not a true daily low/high |
| **Metric units, hard-coded** | Simplicity | No °F option |
| **Single module** | Easy to read in one sitting | Routes, API access and data shaping are mixed together (see below) |

## Configuration and secrets

- `OWM_API_KEY` is read **once, at import time**. Changing `.env` requires a
  restart.
- The key is sent to OpenWeatherMap as the `appid` query parameter (the API
  requires this), over HTTPS. It's never rendered into pages.
- `.env` is gitignored. In production, set the key as an environment variable
  on the host.

## Testing approach

- **Unit tests** call the routes through Flask's test client; no server runs.
- **FakeOWM** (`tests/conftest.py`) replaces `requests.get` for every test. It
  answers according to the endpoint URL, records each call, and fails loudly
  on unexpected URLs, so the suite is offline and repeatable (about 0.1 s).
- **Forecast data is built so mistakes show:** noon readings get distinct
  temperatures and all other readings are -50°, so picking the wrong entry
  fails a test immediately.
- **Known bugs are strict `xfail` tests.** Fixing a bug turns its test into
  `XPASS`, which fails the run until the marker is removed.

## Known limitations

| # | Limitation | Where | Impact |
|---|---|---|---|
| 1 | API error responses aren't checked (geocoding, forecast); `raise_for_status()` on current weather isn't caught | `get_weather()` | Bad key, rate limit, or outage → `500` |
| 2 | No timeouts on `requests.get` | all three calls | A stalled API ties up a worker indefinitely |
| 3 | No input validation | `home()`, `get_weather()` | Whitespace-only search → `500` |
| 4 | Catch-all `/<city>` route | routing | `/favicon.ico` costs a geocoding call; `POST /error` shows weather for "Error" |
| 5 | Server-local "today" vs UTC forecast times | date logic | Wrong date for distant time zones; "noon" is noon UTC |
| 6 | Min/max is the current reading's spread, not the daily range | current weather | Misleading low/high |
| 7 | API key not validated at startup | config | The app starts fine, then fails on the first search |
| 8 | No caching | API access | Three API calls per view; free-tier rate limits apply |
| 9 | Icons missing for `Dust`, `Sand`, `Ash`, `Squall` | `static/assets` | Broken image for those conditions |
| 10 | No logging | everywhere | Failures leave only Flask's traceback |

## Where it's headed

Most of the limitations above come from one thing: `get_weather()` does every
job itself. The natural next step (the exercise's Task 3, a good Plan Mode
candidate) is to split it into layers:

```
routes (main.py)              validate input, call the service, choose a template or redirect
  └─ WeatherService           get_city_weather(city) → CityWeather (dataclass)
       └─ OpenWeatherClient   geocode() / current() / forecast()
                              timeouts, status checks, raises CityNotFound / WeatherAPIError
```

This split pays off in several ways:

- **Errors (#1, #2, #7):** the client sets timeouts and raises custom exceptions,
  and the route turns them into the error page or a `503`.
- **Testing:** the service can be tested with a fake client, without patching `requests`.
- **Features:** caching (#8), daily low/high and local time (#5, #6, using the
  forecast's `city.timezone` offset), and other weather providers each live in
  one place.
