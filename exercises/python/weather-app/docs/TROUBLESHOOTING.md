# Troubleshooting

Find your symptom, then follow the fix. Most problems are the API key, the
port, or the environment.

**Quick diagnosis:** when a page shows *Internal Server Error*, look at the
terminal running `flask`. The last lines of the traceback name the problem,
and this guide is organized by those messages.

| Symptom / error | Likely cause | Jump to |
|---|---|---|
| `KeyError: 0` | Invalid, missing or not-yet-active API key | [Invalid API key](#invalid-api-key) |
| `KeyError: 'list'` | Forecast call failed (rate limit or key) | [Rate limited](#rate-limited-429) |
| `HTTPError: 401` / `429` / `5xx` | Current-weather call failed | [Invalid API key](#invalid-api-key), [Rate limited](#rate-limited-429) |
| `JSONDecodeError` | Something other than OpenWeatherMap answered | [Blocked network / proxy](#jsondecodeerror-blocked-network-or-proxy) |
| `ConnectionError` / request hangs | No network, DNS, or firewall | [Network problems](#network-problems) |
| Blank page or `403` at `localhost:5000` (Mac) | AirPlay Receiver owns port 5000 | [macOS port 5000](#macos-localhost5000-shows-a-blank-page-or-403) |
| `Address already in use` | Another server on port 5000 | [Port in use](#address-already-in-use) |
| `ModuleNotFoundError: flask` | Virtual environment not active | [Missing modules](#modulenotfounderror) |
| Every city goes to "does not exist" | Real no-match, or a typo | [City not found](#a-real-city-shows-this-city-does-not-exist) |
| Broken weather icon | Condition without an icon | [Broken icon](#broken-weather-icon) |
| Wrong date / odd forecast days | Time zone handling | [Dates and forecast](#wrong-date-or-unexpected-forecast-days) |

---

## Invalid API key

**Symptoms:** every search gives *Internal Server Error*. The traceback ends with
`KeyError: 0` at `lat = location_data[0]['lat']`, or with
`requests.exceptions.HTTPError: 401`.

**Why:** OpenWeatherMap answers `{"cod": 401, "message": "Invalid API key"}`. The
app expects a list of matches and crashes reading the error object.

**Check the key directly:**

```bash
source .env   # or: export OWM_API_KEY=...
curl -s "https://api.openweathermap.org/geo/1.0/direct?q=London&limit=1&appid=$OWM_API_KEY"
```

| Output | Meaning |
|---|---|
| `[{"name":"London",...}]` | Key works. Restart the Flask server so it picks up the key. |
| `{"cod":401,"message":"Invalid API key..."}` | Key wrong, or **not active yet** (new keys take 10 minutes to a couple of hours) |
| empty output / `{"cod":401}` with an empty key | `OWM_API_KEY` isn't set |

**Fixes:**

1. `.env` must be in the `weather-app` folder (next to `main.py`) and contain
   exactly `OWM_API_KEY=yourkey`: no quotes, no spaces around `=`.
2. **Restart the server after editing `.env`.** It's read once at startup, and the
   `--debug` reloader only watches `.py` files.
3. Check whether a stale `OWM_API_KEY` environment variable is set in your shell:
   `echo $OWM_API_KEY`. A real environment variable **overrides** `.env`.
4. Brand-new key? Wait, then re-run the `curl` check.

## Rate limited (429)

**Symptoms:** worked earlier, now *Internal Server Error*, with
`HTTPError: 429` or `KeyError: 'list'`.

**Why:** each city page makes three API calls, and the free plan limits calls
per minute and per month (current limits: <https://openweathermap.org/price>).
Rapid refreshing or test scripts against the live API can hit the per-minute
limit.

**Fix:** wait a minute. To avoid it, don't hit the live API in loops; use the
offline test suite (`pytest`), which never calls OpenWeatherMap.

## JSONDecodeError: blocked network or proxy

**Symptoms:** `requests.exceptions.JSONDecodeError: Expecting value: line 1 column 1`
at `location_response.json()`.

**Why:** the response wasn't JSON. Something between you and OpenWeatherMap
answered instead: a corporate proxy, a captive portal, or a sandbox firewall
returning an HTML or text block page.

**Check:**

```bash
curl -s https://api.openweathermap.org/ | head -3
```

If you see a proxy or firewall message instead of OpenWeatherMap's response,
allow `api.openweathermap.org` (port 443). In the course's Docker sandbox, run
`sbx policy approval ls` on the host and approve it.

## Network problems

**Symptoms:** `requests.exceptions.ConnectionError`, `Name or service not known`,
or the page **hangs** with no error.

**Why:** no route to `api.openweathermap.org`. The app sets **no timeout**, so a
stalled connection hangs instead of failing.

**Fix:** check connectivity with
`curl -sI https://api.openweathermap.org/ | head -1`, check VPN and proxy
settings, then retry. Press Ctrl+C to stop a hung dev server.

## macOS: `localhost:5000` shows a blank page or 403

**Why:** macOS **AirPlay Receiver** listens on port 5000 (IPv4 and IPv6).
`localhost` tries IPv6 first and reaches AirPlay, not Flask.

**Fixes (pick one):**

- Use `http://127.0.0.1:5000`.
- Run on another port: `flask --app main run --debug --port 5001`.
- Turn it off: System Settings → General → AirDrop & Handoff → AirPlay Receiver.

Check what owns the port: `lsof -nP -iTCP:5000 -sTCP:LISTEN` (`ControlCe` is AirPlay).

## Address already in use

**Symptoms:** `OSError: [Errno 48] Address already in use` (macOS) or
`[Errno 98]` (Linux) when starting Flask.

**Fix:** another process has the port, often a previous Flask server.

```bash
lsof -nP -iTCP:5000 -sTCP:LISTEN      # find it
kill <PID>                            # stop it
# or simply: flask --app main run --debug --port 5001
```

## ModuleNotFoundError

**Symptoms:** `ModuleNotFoundError: No module named 'flask'` (or `requests`,
`dotenv`, `pytest`), or `flask: command not found`.

**Fix:** activate the virtual environment and install the dependencies:

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
which python   # should point inside .venv
```

**Shared folder between a sandbox and your Mac?** A `.venv` created inside a
Linux sandbox won't run on macOS, and vice versa (`bad interpreter`, `exec
format error`). Make a separate environment on each side, under a different
name, for example `python3 -m venv venv` on the Mac (`venv/` is gitignored too).

## A real city shows "This city does not exist"

**Why:** the geocoding API returned no matches.

- Check the spelling. The API matches names, not partial text.
- Use a name the API knows. English and local names both work (`Munich`,
  `München`), and so do some common nicknames (`NYC`), but not every
  abbreviation does.
- For duplicates, add a country code: `Paris,US`, `Portland,OR,US`.
- Seeing this for **every** city, including London? Check the server log. If it
  shows `GET /favicon.ico` redirecting to `/error`, that's the browser's icon
  request (harmless). Otherwise test the key with the `curl` check above.

## Broken weather icon

**Why:** the page loads `static/assets/<condition>.png`. Icons exist for Clear,
Clouds, Drizzle, Fog, Haze, Mist, Rain, Smoke, Snow, Thunderstorm and Tornado.
OpenWeatherMap can also report **Dust, Sand, Ash, Squall**, which have no icon.

**Fix:** add a PNG with that name (lowercase) to `static/assets/`, or map the
missing conditions to an existing icon in the template.

## Wrong date or unexpected forecast days

**Why:** the date comes from the **server's** clock, while forecast timestamps
are **UTC**, and "noon" means 12:00 UTC. For cities far from the server's time
zone, the date can be off by one and the noon reading may be from the middle of
the night locally. This is a known limitation (see
[architecture-overview.md](architecture-overview.md#known-limitations)).

The first forecast column always shows *today* using the current conditions,
followed by up to four later days. Fewer than four means the API returned
fewer noon entries, which can happen near the end of its 5-day window.

## Min/max looks wrong ("1° - 4°" in summer)

**Why:** those values are the current reading's `temp_min`/`temp_max`, which is the
spread across the city area **right now**, not the day's low and high. This is
expected with the current code (implementing a real daily low/high is a bonus challenge).

## Tests

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'main'` | Run `pytest` from the `weather-app` folder; `pytest.ini` sets the path |
| `ModuleNotFoundError: conftest` | Same: run from `weather-app`, not from `tests/` |
| A test shows **XPASS** and the run fails | You fixed a known bug. Delete that test's `@known_bug(...)` line |
| Tests seem to call the real API | They can't: FakeOWM replaces `requests.get` for every test and fails on unknown URLs |
| `--cov` not recognized | `pip install pytest-cov` |

## Still stuck?

1. Read the full traceback in the Flask terminal. The last frame inside
   `main.py` shows which step failed.
2. Reproduce with `curl -i http://127.0.0.1:5000/<City>` to see the status code.
3. Check the API on its own with the `curl` key check above.
4. Run `pytest -v`. If the tests pass but the live app fails, the problem is
   the environment (key, network, port), not the code.
