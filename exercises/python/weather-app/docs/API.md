# HTTP API Reference

The app serves **server-rendered HTML pages**, not a JSON API. Every endpoint
returns `text/html` (or a redirect). There is no authentication: the
OpenWeatherMap key stays on the server and is never sent to the browser.

Base URL in development: `http://127.0.0.1:5000`

| Method | Path | Handler | Purpose |
|---|---|---|---|
| `GET` | [`/`](#get-) | `home()` | Search form |
| `POST` | [`/`](#post-) | `home()` | Submit a search → redirect to `/<city>` |
| `GET` | [`/<city>`](#get-city) | `get_weather()` | Weather page for a city |
| `GET` | [`/error`](#get-error) | `error()` | "City not found" page |
| `GET` | [`/favicon.ico`](#get-faviconico) | `favicon()` | Empty `204` for the browser's icon request |
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
| `search` | string | no | City name. Leading and trailing spaces are trimmed; title-casing happens on `/<city>`. |

**Responses**

| Status | `Location` | When |
|---|---|---|
| `302 Found` | `/<city>`, percent-encoded | `search` has any non-space text (`"  London "` → `/London`) |
| `302 Found` | `/` | `search` empty, whitespace-only, or missing (no API calls) |

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

```bash
$ curl -i -X POST --data-urlencode 'search=   ' http://127.0.0.1:5000/
HTTP/1.1 302 FOUND
Location: /
```

---

## `GET /<city>`

Looks the city up and renders the weather page (`templates/city.html`).
GET only: `POST` gets `405 Method Not Allowed`.

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
| Date | Current time in the **city's** time zone (`timezone` offset from call 2) | `Friday, November 13`; Tokyo may already show Saturday |
| Current temperature | `main.temp` (call 2) | Rounded, `42ºF` (`ºC` if metric) |
| Condition + icon | `weather[0].main` (call 2) | `Clouds`, icon `static/assets/clouds.png` (see **Icons** below) |
| Today's low - high | Lowest `temp_min` and highest `temp_max` of the current reading and the rest of today's forecast readings (calls 2 and 3) | Rounded, `38° - 43°` |
| Wind | `wind.speed` (call 2) | `5.75 mph` (`meter/sec` if metric) |
| Forecast, first column | Today's weekday (city time) + current conditions | `Fri 41º` |
| Forecast, next 4 columns | The next 4 days in city time. Readings are grouped by local date (`dt` + `timezone`); each day shows its highest `temp_max` and lowest `temp_min`, and the icon of the reading closest to local noon (call 3) | `Sat 47º 34º` (high, then low, dimmed) |

**Responses**

| Status | When |
|---|---|
| `200 OK` | City found and all three calls succeeded |
| `302 Found` → `/error` | Geocoding returned no matches (an empty list) |
| `302 Found` → `/` | The name is empty or only spaces (e.g. `/%20%20`); no API calls |
| `404 Not Found` | Path has more than one segment (`/a/b`) |
| `503 Service Unavailable` | Any OpenWeatherMap failure: key missing or invalid (401), rate limit (429), server error, network error, no answer within 10 seconds, or a reply that isn't JSON. Renders `error.html` with "Weather data is unavailable right now. Please try again later." The reason is logged on the server, with the API key redacted. |

```bash
$ curl -i http://127.0.0.1:5000/New%20Haven
HTTP/1.1 200 OK
Content-Type: text/html; charset=utf-8

$ curl -s http://127.0.0.1:5000/New%20Haven | sed -e 's/<[^>]*>/ /g' | tr -s ' \n' ' '
 Weather Forecast CHANGE CITY New Haven Friday, November 13 41ºF Clouds 38° - 43°
 6.91 mph 5-DAY FORECAST Fri 41º Sat 47º 34º Sun 47º 36º Mon 47º 34º Tue 52º 33º ...

$ curl -i http://127.0.0.1:5000/Xyzzyville
HTTP/1.1 302 FOUND
Location: /error
```

**Icons.** `icon_for()` picks `static/assets/<name>.png` for a condition.
Eleven conditions have their own icon (`Clear`, `Clouds`, `Drizzle`, `Fog`,
`Haze`, `Mist`, `Rain`, `Smoke`, `Snow`, `Thunderstorm`, `Tornado`). The other
four map to a similar one: `Dust` and `Sand` → haze, `Ash` → smoke,
`Squall` → wind. Anything else falls back to clouds, so an icon is never broken.

---

## `GET /error`

Renders the "This city does not exist. Please try again." page
(`templates/error.html`; the same template, with a different message and a
503 status, is used when OpenWeatherMap is unavailable) with a **CHANGE CITY** link back to `/`. Makes no API
calls. Normally reached by the redirect from `/<city>`.

| Status | Body |
|---|---|
| `200 OK` | Error page |

`POST /error` returns `405 Method Not Allowed`.

---

## `GET /favicon.ico`

Browsers request `/favicon.ico` automatically on every page. The app has no
icon, so this returns **`204 No Content`** with an empty body, without a
weather lookup. (Without this route, `/<city>` would treat `favicon.ico` as a
city name and spend a geocoding call on each page load.)

| Status | Body |
|---|---|
| `204 No Content` | Empty |

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
| `POST` (or `PUT`, ...) on `/<city>` or `/error` | `405 Method Not Allowed`, `Allow: HEAD, OPTIONS, GET` |
| `HEAD` on any route | Same status and headers as `GET`, no body (for `/<city>`, the three API calls still run) |

## Known issues

None known in the HTTP interface. Design limitations (no caching, and so on)
are listed in [architecture-overview.md](architecture-overview.md#known-limitations);
symptoms and fixes are in [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

Today's low covers the current reading and the *rest* of today: the free
endpoints don't return readings from earlier in the day.
