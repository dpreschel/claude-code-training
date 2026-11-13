# Weather App

A small Flask web app that shows the current weather and a 4-day forecast for
any city, using the [OpenWeatherMap](https://openweathermap.org/api) API.

Type a city, get a page with the current temperature, conditions, the min/max
range, wind speed, and the noon forecast for the next four days. Unknown cities
go to a friendly "city not found" page.

> This folder holds the developer documentation. The project's original
> README (screenshots, the author's reflection, image and icon credits) is
> [`../README.md`](../README.md).

| Document | What's in it |
|---|---|
| **README.md** (this file) | Setup, usage, examples, tests |
| [API.md](API.md) | Every HTTP endpoint: methods, parameters, responses |
| [architecture-overview.md](architecture-overview.md) | Components, data flow, dependencies, design decisions, known limitations |
| [architecture.md](architecture.md) | Mermaid diagrams: components, request sequence, `get_weather()` flow |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Common problems and how to fix them |

---

## Features

- Search any city by name; the name is title-cased (`new haven` → `New Haven`)
- Current conditions: temperature, condition with icon, min/max, wind
  (°F and mph by default, or °C and m/s with `UNITS=metric`)
- 4-day forecast using each day's 12:00 (UTC) reading
- Bookmarkable city URLs: `http://127.0.0.1:5000/London`
- Responsive layout (CSS grid, flexbox, media queries); no JavaScript
- Unit test suite that runs offline against a fake OpenWeatherMap

## Tech stack

| Layer | Technology |
|---|---|
| Web framework | Flask 3.1 (Werkzeug, Jinja2) |
| HTTP client | requests 2.34 |
| Configuration | python-dotenv (`.env` file) |
| Production server | gunicorn (see `Procfile`) |
| Tests | pytest 9.2, Flask test client |
| External API | OpenWeatherMap: Geocoding, Current Weather, 5-day Forecast (free tier) |

## Project layout

```
weather-app/
├── main.py                 # The whole app: config, three routes, API calls
├── templates/
│   ├── index.html          # Search form
│   ├── city.html           # Weather + forecast page
│   └── error.html          # "City not found"
├── static/
│   ├── css/main.css        # All styling
│   └── assets/             # Backgrounds and one icon per weather condition
├── tests/
│   ├── conftest.py         # Fixtures + FakeOWM (fake OpenWeatherMap)
│   └── test_main.py        # Unit tests
├── docs/                   # This documentation
├── requirements.txt        # Runtime dependencies
├── requirements-dev.txt    # + test dependencies
├── pytest.ini              # Test discovery settings
├── Procfile                # gunicorn command for Heroku-style hosts
├── .env.example            # Template for .env (committed)
└── .env                    # Your settings and API key (create it; gitignored)
```

---

## Setup

### Prerequisites

- **Python 3.10+** (developed and tested on 3.15)
- A free **OpenWeatherMap API key**

### 1. Get an API key

1. Sign up at <https://openweathermap.org> (the free plan is enough).
2. Open **API keys** from your account menu and copy the default key.
3. **New keys can take from 10 minutes to a couple of hours to activate.** Until then,
   the API answers `401 Invalid API key` (see [Troubleshooting](TROUBLESHOOTING.md#invalid-api-key)).

### 2. Create a virtual environment and install dependencies

```bash
cd exercises/python/weather-app
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt   # or requirements.txt if you won't run tests
```

With [uv](https://docs.astral.sh/uv/) instead:

```bash
uv venv .venv && uv pip install -p .venv -r requirements-dev.txt
```

### 3. Configure `.env`

Copy the template and put your key in it:

```bash
cp .env.example .env
```

```text
OWM_API_KEY=your-api-key-here   # required
UNITS=imperial                  # imperial (°F, mph) or metric (°C, m/s)
FLASK_RUN_PORT=5000             # dev server port
```

Only `OWM_API_KEY` is required; the other two have defaults. See the
[configuration reference](#configuration-reference) for details.

`.env` is gitignored. Real environment variables with the same names work too
and take precedence over the file.

### 4. Run

```bash
flask --app main run --debug
```

Open <http://127.0.0.1:5000> (or the port you set in `FLASK_RUN_PORT`).

> **macOS:** use `127.0.0.1:5000`, not `localhost:5000`. AirPlay Receiver also
> listens on port 5000 and answers `localhost`. Alternatively set
> `FLASK_RUN_PORT=5001` in `.env`, or turn AirPlay Receiver off.

`--debug` enables the auto-reloader and the in-browser debugger. The reloader
watches `.py` files only: **restart the server after editing `.env`.**

---

## Usage

| You do | You get |
|---|---|
| Open `/` | The search form |
| Type `London`, press Enter | Redirect to `/London` → weather page |
| Type `new haven` | Redirect to `/new%20haven` → page titled **New Haven** |
| Open `/Paris` directly | Weather for Paris (bookmarkable) |
| Search a city that doesn't exist | Redirect to `/error` → "This city does not exist" |
| Click **CHANGE CITY** | Back to the search form |

**Ambiguous names:** the app uses the first match OpenWeatherMap returns.
`Paris` gives Paris, France. To pick another, add a country code (or
`state,country` for the US), which the geocoding API understands: `/Paris,US`
gives Paris, Texas. The page heading then reads "Paris,us", because the name
is title-cased word by word and `Paris,US` counts as one word.

## Examples

### Browser

```
http://127.0.0.1:5000/
http://127.0.0.1:5000/London
http://127.0.0.1:5000/New%20Haven
http://127.0.0.1:5000/Paris,US
```

### Command line

Search through the form, as a browser does. The response is a redirect:

```bash
$ curl -i -X POST -d 'search=new haven' http://127.0.0.1:5000/
HTTP/1.1 302 FOUND
Location: /new%20haven
```

Fetch a city page and strip the HTML to see the data:

```bash
$ curl -s http://127.0.0.1:5000/New%20Haven | sed -e 's/<[^>]*>/ /g' | tr -s ' \n' ' '
 Weather Forecast CHANGE CITY New Haven Friday, November 13 42ºF Clouds 40° - 43°
 5.75 mph 5-DAY FORECAST Fri 42º Sat 34º Sun 36º Mon 34º Tue 33º ...
```

An unknown city:

```bash
$ curl -i http://127.0.0.1:5000/Xyzzyville
HTTP/1.1 302 FOUND
Location: /error
```

Every endpoint, with full request/response details: [API.md](API.md).

---

## Running the tests

```bash
source .venv/bin/activate
pytest                    # 20 passed, 8 xfailed
pytest -v                 # one line per test
pytest -rx                # list the known bugs (xfail) with reasons
pytest -k new_haven       # tests whose name matches
```

The tests never touch the network or need an API key. `tests/conftest.py`
replaces `requests.get` with **FakeOWM**, which returns canned responses by
endpoint URL and records every call so tests can check what the app sent.

Tests marked **xfail** document known bugs (unhandled API errors, no timeouts,
etc.; see [architecture-overview.md](architecture-overview.md#known-limitations)).
They are strict: when a fix makes one pass, pytest reports **XPASS** as a
failure, which is the cue to delete its `@known_bug` marker.

Coverage (optional):

```bash
pip install pytest-cov
pytest --cov=main --cov-report=term-missing
```

## Deployment

The `Procfile` runs the app under gunicorn, for Heroku and similar hosts:

```
web: gunicorn main:app
```

Set `OWM_API_KEY` as a config variable on the host (don't deploy `.env`). To try
gunicorn locally:

```bash
gunicorn main:app --bind 127.0.0.1:8000
```

Don't use `flask run --debug` or `python main.py` in production: the debugger
allows arbitrary code execution from the browser.

## Configuration reference

All settings go in `.env` (template: `.env.example`) or in real environment
variables, which take precedence. They're read **once at startup**: restart the
server after changing them.

| Setting | Values | Default | Notes |
|---|---|---|---|
| `OWM_API_KEY` | your key | *(none)* | **Required.** Not validated: a missing key shows up as an error on the first search. |
| `UNITS` | `imperial`, `metric` | `imperial` | `imperial`: °F and mph. `metric`: °C and meter/sec. Sent to OpenWeatherMap, which converts the numbers; the page labels follow automatically. Case-insensitive. **Any other value also means imperial**, and the server logs a warning (e.g. `UNITS='xxx' is not 'metric' or 'imperial'; using imperial`). |
| `FLASK_RUN_PORT` | port number | `5000` | Used by `flask run` and `python main.py`. A `--port` flag on the command line overrides it. Not used by gunicorn, which binds to `$PORT` or its `--bind` option. |

Examples:

```text
# Celsius on port 5001
UNITS=metric
FLASK_RUN_PORT=5001
```

```bash
# One-off override without editing .env
UNITS=metric flask --app main run --debug --port 5002
```

## Further reading

- [OpenWeatherMap API documentation](https://openweathermap.org/api)
- [Flask documentation](https://flask.palletsprojects.com/)
- [pytest documentation](https://docs.pytest.org/)
