# Race suite validation (T7)

All 13 overlays are implemented, committed in six local work units on top of the
preserved baseline, and covered by automated tests with a fake SDK, a stub DOM
and one headless-browser layout probe. **No live iRacing, desktop launcher or
OBS session has been run.** Those checks are listed at the end. Nothing here is
a native review approval.

## Run the checks

```bash
python -B -m unittest discover -s tests -p "test_suite_integration.py"
python -B -m unittest discover -s tests -p "test_*.py"
node --test tests/test_accuracy_frontend.cjs tests/test_themes.cjs tests/test_fuel_session_frontend.cjs tests/test_battle_standings_frontend.cjs tests/test_pit_weather_frontend.cjs tests/test_broadcast_driver_frontend.cjs tests/test_suite_integration.cjs
```

| Command | Result when this unit was finished |
|---------|------------------------------------|
| integration Python | 16 tests OK |
| full Python | 249 tests OK |
| Node (7 files) | 130 tests pass, 0 fail |

The full Python run prints `Error emitting ... : boom`. That is the intentional
failure-isolation test (one failing emit must not block other overlays), not a
failure.

`tests/test_suite_integration.cjs` starts `python -B tests/test_suite_integration.py --dump-wire`
to get real backend payloads and renders them with the real overlay scripts. If
`python` is not on `PATH` those tests are skipped and say so.

## What the integration tests cover

| Area | Where |
|------|-------|
| 13 overlays discovered, unique names, query-free URLs, one namespace each | `test_suite_integration.py` |
| One frozen fake-SDK tick reaches each overlay on its own event only; legacy input keeps its flat shape | `test_suite_integration.py` |
| Missing telemetry is `null`, non-finite numbers never reach the wire | `test_suite_integration.py` |
| Camera switch and session change change only the views they should | `test_suite_integration.py` |
| No simulator: nothing is emitted; losing the sim stops the stream | `test_suite_integration.py` |
| Every page and its local assets serve; Original is the default, `?theme=glass` pins Glass | `test_suite_integration.py` |
| Backend payloads render the same in both themes, with no `NaN`/`undefined`, and clear on stale, disconnect or null | `test_suite_integration.cjs` |

## Layout probe (headless Chromium)

Python Playwright 1.58 with its bundled Chromium 145 was already installed. A
throwaway server on an ephemeral localhost port fed the seven new overlays
**simulated** fixture data (never live data), once with empty data and once with
representative data, in both themes. It recorded computed grid columns, text
clipping, elements outside the card, JS errors and screenshots.

Result: no clipping, no overflow and no JS errors in 28 page states. One layout
defect was found and fixed: `fuel_finish.css` styled `.fuel-grid`, but the shared
`.rah-grid` rule has the same specificity and loads later, so the card rendered 3
columns instead of the designed 4. It now uses `.rah-grid.fuel-grid` like the
other four grid widgets, pinned by a test in `tests/test_fuel_session_frontend.cjs`.

The probe scripts and screenshots are scratch files under `.git/t7-scratch/` and
are not part of the repository. This is not a substitute for looking at the
overlays in the real launcher and in OBS.

## Work-unit boundaries

Copied from the task tracker. Each unit keeps behavior, tests and docs together,
so units exceed 400 lines rather than being split by file type.

| Unit | Commit | Range | Authored lines |
|------|--------|-------|----------------|
| Baseline preserved | `5330373` | existing source before the feature | 1,184 |
| T1 accuracy fixes | `4f0629d` | `5330373..4f0629d` | 1,030 |
| T2 themes and launcher selector | `1cc0048` | `4f0629d..1cc0048` | 1,245 |
| T3 Fuel & Finish, Session Strip | `43df659` | `1cc0048..43df659` | 2,042 |
| T4 Battle & Pace, Standings | `f840359` | `43df659..f840359` | 2,491 |
| T5 Pit Assistant, Weather | `572124c` | `f840359..572124c` | 1,635 |
| T6 Broadcast Driver Card | `d4726ec` | `572124c..d4726ec` | 1,191 |
| T7 integration tests and docs | pending | `d4726ec..` | see the tracker |

## The 13 overlays

| Overlay | Folder | Event | Details |
|---------|--------|-------|---------|
| Input Telemetry | `input_telemetry` | `telemetry_update` | existing |
| Relative | `relative` | `relative_update` | existing |
| Radar | `radar` | `radar_update` | existing |
| BlindSpot | `blindspot` | `blindspot_update` | existing |
| Track Map | `track_map` | `track_map_update` | existing |
| Laptime graph | `laptime_graph` | `laptime_graph_update` | existing |
| Fuel & Finish | `fuel_finish` | `fuel_finish_update` | [fuel-session.md](fuel-session.md) |
| Session Strip | `session_strip` | `session_strip_update` | [fuel-session.md](fuel-session.md) |
| Battle & Pace | `battle_pace` | `battle_pace_update` | [battle-standings.md](battle-standings.md) |
| Multiclass Standings | `standings` | `standings_update` | [battle-standings.md](battle-standings.md) |
| Pit Assistant | `pit_assistant` | `pit_assistant_update` | [pit-weather.md](pit-weather.md) |
| Weather | `weather` | `weather_update` | [pit-weather.md](pit-weather.md) |
| Broadcast Driver Card | `broadcast_driver` | `broadcast_driver_update` | [broadcast-driver.md](broadcast-driver.md) |

## SDK assumptions that are still unverified

Variable names and units come from the pyirsdk documentation, not from a running
simulator. Each overlay doc has the full list under "Limitations and live
validation".

- `SessionLapsRemainEx` counting rule and the "unlimited" sentinels.
- `CarIdxF2Time` and `CarIdxLastLapTime` timing in a real multiclass race.
- `DriverInfo` class fields and `TrackPitSpeedLimit` unit strings per track.
- `PitSvFlags` / `PlayerCarPitSvStatus` values during a real stop, and kWh fuel on electric cars.
- `Precipitation`, `TrackWetness` and `WindDir` ranges and compass convention.
- `CamCarIdx` behaviour when the camera is on no car.

## Manual checklist: iRacing, desktop launcher, OBS

Not run. Do these with the simulator and mark them off.

- [ ] Start `python src/app.py` with iRacing running. Open all 13 overlays from the launcher.
- [ ] Fuel & Finish: burn per lap and laps of fuel stay sensible across a pit stop, tow, reset and session change.
- [ ] Session Strip: laps or time remaining, flag and state match the sim in a lap-limited and a timed session.
- [ ] Battle & Pace and Standings: run a multiclass race and check class order, gaps and the lapped-car intervals.
- [ ] Pit Assistant: pit speed limit margin on pit entry and exit; service flags during a real stop.
- [ ] Weather: values change in a dynamic-weather session. They are observed values, not a forecast.
- [ ] Broadcast Driver Card: switch cars in replay or spectator mode; the card follows the camera and never shows your own inputs.
- [ ] Original is the default; the launcher theme selector opens Glass overlays with `?theme=glass`.
- [ ] Glass in the desktop launcher and in an OBS browser source: readable, no clipping. Blur never shows the game behind a transparent window.
- [ ] Copy the pinned URL from the launcher into an OBS browser source and confirm it loads.
- [ ] Close the sim: overlays show "Stale: no data" within about 3 seconds and stop showing numbers.

## Known limits (reported, not fixed here)

- With a connected SDK that exposes nothing yet, `session_strip`, `pit_assistant` and `weather` show every value as `--` but their status chip still reads "Live". No number is invented.
- The legacy Input Telemetry overlay shows `0` values in that same state, as it did before this work.
- A very long pit speed limit string, a delayed opponent lap update and wind direction near 360 degrees have small known rough edges described in the tracker.
- The `dist/` executable was not rebuilt by this work. Do not assume it matches the source.
