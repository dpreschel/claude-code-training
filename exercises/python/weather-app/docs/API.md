# HTTP API Reference

The app serves **server-rendered HTML pages**, not a JSON API. Every endpoint
returns `text/html` (or a redirect). There is no authentication: the
OpenWeatherMap key stays on the server and is never sent to the browser.

Base URL in development: `http://127.0.0.1:5000`

| Method | Path | Handler | Purpose |
|---|---|---|---|
| `GET` | [`/`](#get-) | `home()` | Search form |
| `POST` | [`/`](#post-) | `home()` | Submit a search → redirect to `/<city>` |
| `GET`, `POST` | [`/<city>`](#get-city) | `get_weather()` | Weather page for a city |
| `GET` | [`/error`](#get-error) | `error()` | "City not found" page |
| `GET` | [`/static/<path>`](#get-staticpath) | Flask built-in | CSS, images, icons |

Flask also answers `HEAD` and `OPTIONS` for every route automatically.

---

## `GET /`

Renders the search form (`templates/index.html`). Makes no API calls.

**Response**

| Status | Body |
|---|---|
| `200 OK` | Search page, with a form field `search` that POSTs back to `/` |

```bash
$ curl -i http://127.0.0.1:5000/
HTTP/1.1 200 OK
Content-Type: text/html; charset=utf-8
```

---

## `POST /`

Receives the search form and redirects to the city page (Post/Redirect/Get).
Renders nothing itself and makes no API calls.

**Request body** (`application/x-www-form-urlencoded`)

| Field | Type | Required | Description |
|---|---|---|---|
| `search` | string | no | City name as typed. Passed through unchanged; title-casing happens on `/<city>`. |

**Responses**

| Status | `Location` | When |
|---|---|---|
| `302 Found` | `/<city>`, percent-encoded | Any non-empty `search` |
| `302 Found` | `/` | `search` empty or missing |

```bash
$ curl -i -X POST -d 'search=London' http://127.0.0.1:5000/
HTTP/1.1 302 FOUND
Location: /London

$ curl -i -X POST -d 'search=new haven' http://127.0.0.1:5000/
HTTP/1.1 302 FOUND
Location: /new%20haven

$ curl -i -X POST -d 'search=' http://127.0.0.1:5000/
HTTP/1.1 302 FOUND
Location: /
```

> **Known issue:** a whitespace-only search (`search=   `) redirects to
> `/%20%20%20`, which fails with `500` (see `/<city>` below).

---

## `GET /<city>`

Looks the city up and renders the weather page (`templates/city.html`).
`POST` is also accepted and behaves exactly like `GET`.

**Path parameter**

| Name | Type | Description |
|---|---|---|
| `city` | string, one path segment | City name, percent-encoded. Title-cased with `string.capwords` before use (`new haven` → `New Haven`). May include a country or state code: `Paris,US`, `Springfield,IL,US`. Cannot contain `/`. |

**What the server does:** three OpenWeatherMap calls, one after another, using
the configured `OWM_API_KEY`:

| # | OpenWeatherMap endpoint | Parameters sent | Used for |
|---|---|---|---|
| 1 | `GET /geo/1.0/direct` | `q=<City Name>`, `limit=3`, `appid` | Latitude and longitude of the **first** match |
| 2 | `GET /data/2.5/weather` | `lat`, `lon`, `units` (from `UNITS`), `appid` | Current conditions |
| 3 | `GET /data/2.5/forecast` | `lat`, `lon`, `units` (from `UNITS`), `appid` | 4-day forecast |

All three go to `https://api.openweathermap.org`. Examples below use the
default `UNITS=imperial`; with `UNITS=metric` the page shows `ºC` and
`meter/sec` instead of `ºF` and `mph`.

**Page contents (`city.html`)**

| Shown | Source | Format |
|---|---|---|
| City heading | `capwords(city)` | `New Haven` |
| Date | Server's local clock | `Friday, November 13` |
| Current temperature | `main.temp` (call 2) | Rounded, `42ºF` (`ºC` if metric) |
| Condition + icon | `weather[0].main` (call 2) | `Clouds`, icon `static/assets/clouds.png` |
| Min - max | `main.temp_min`, `main.temp_max` (call 2) | Rounded, `40° - 43°` |
| Wind | `wind.speed` (call 2) | `5.75 mph` (`meter/sec` if metric) |
| Forecast, first column | Today's weekday + current conditions | `Fri 42º` |
| Forecast, next 4 columns | Entries with `dt_txt` ending `12:00:00`, excluding today's date (call 3) | `Sat 34º` |

**Responses**

| Status | When |
|---|---|
| `200 OK` | City found and all three calls succeeded |
| `302 Found` → `/error` | Geocoding returned no matches (an empty list) |
| `404 Not Found` | Path has more than one segment (`/a/b`) |
| `500 Internal Server Error` | Any OpenWeatherMap failure: invalid or missing key (401), rate limit (429), server error, network error, or a whitespace-only city. **These are not handled yet**; see [Known issues](#known-issues). |

```bash
$ curl -i http://127.0.0.1:5000/New%20Haven
HTTP/1.1 200 OK
Content-Type: text/html; charset=utf-8

$ curl -s http://127.0.0.1:5000/New%20Haven | sed -e 's/<[^>]*>/ /g' | tr -s ' \n' ' '
 Weather Forecast CHANGE CITY New Haven Friday, November 13 42ºF Clouds 40° - 43°
 5.75 mph 5-DAY FORECAST Fri 42º Sat 34º Sun 36º Mon 34º Tue 33º ...

$ curl -i http://127.0.0.1:5000/Xyzzyville
HTTP/1.1 302 FOUND
Location: /error
```

**Icons.** The page loads `static/assets/<condition>.png`, with the condition
lowercased. Icons exist for `Clear`, `Clouds`, `Drizzle`, `Fog`, `Haze`, `Mist`,
`Rain`, `Smoke`, `Snow`, `Thunderstorm` and `Tornado`. OpenWeatherMap can also
return `Dust`, `Sand`, `Ash` and `Squall`, which show a broken image.

---

## `GET /error`

Renders the "This city does not exist. Please try again." page
(`templates/error.html`) with a **CHANGE CITY** link back to `/`. Makes no API
calls. Normally reached by the redirect from `/<city>`.

| Status | Body |
|---|---|
| `200 OK` | Error page |

> **Quirk:** `POST /error` does *not* reach this handler. `/error` only allows
> `GET`, so Flask falls through to `/<city>` (which accepts `POST`) and shows the
> weather for a place named "Error".

---

## `GET /static/<path>`

Flask's built-in static file handler for `static/`: `css/main.css`, background
images, and the weather icons in `assets/`.

| Status | When |
|---|---|
| `200 OK` | File exists (`Content-Type` from the extension, e.g. `text/css`) |
| `404 Not Found` | No such file |

---

## Other methods

| Request | Response |
|---|---|
| `PUT`, `DELETE`, `PATCH` on `/` | `405 Method Not Allowed`, `Allow: HEAD, POST, GET, OPTIONS` |
| `HEAD` on any route | Same status and headers as `GET`, no body (for `/<city>`, the three API calls still run) |

## Known issues

These are documented by strict `xfail` tests in `tests/test_main.py`:

| Issue | Effect |
|---|---|
| OpenWeatherMap error responses aren't checked | Bad key, rate limit, or outage → `500` instead of an error page |
| No timeouts on outgoing requests | A slow API stalls the request indefinitely |
| Whitespace-only city | `500` |
| `/favicon.ico` (requested automatically by browsers) is treated as a city | One wasted geocoding call per page load; redirects to `/error` |
| Missing `OWM_API_KEY` isn't detected at startup | Every search fails with `500` |

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for symptoms and fixes.
