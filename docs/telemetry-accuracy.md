# Telemetry accuracy fixes

This document describes the accuracy corrections applied to the telemetry
pipeline (ODD task T1). Every fix keeps existing public payload keys working;
new keys are additive and optional so older overlay payloads never break.

Run the regression suites with the standard library runners only:

```bash
python -m unittest discover -s tests -p "test_*.py" -v
node --test tests/test_accuracy_frontend.cjs
```

## CarLeftRight side decoding (radar + blindspot)

`CarLeftRight` is an enum, not a bitfield. The overlays previously decoded it
with bitwise tests, which reported phantom alerts (for example "clear" lit the
left-side alert). Decoding now follows the SDK definition:

| Value | Meaning              | Left alert | Right alert |
|-------|----------------------|------------|-------------|
| 0     | off                  | no         | no          |
| 1     | clear                | no         | no          |
| 2     | car left             | yes        | no          |
| 3     | car right            | no         | yes         |
| 4     | cars on each side    | yes        | yes         |
| 5     | two cars left        | yes        | no          |
| 6     | two cars right       | no         | yes         |

`radar_data` and `blindspot_data` keep their existing keys (`left_alert`,
`right_alert`, `both_alert`, `message`, `active`) with corrected values.

## Completed-lap history (laptime graph)

Lap history is recorded from `LapLastLapTime` only when the `Lap` counter
actually advances (a completed-lap transition). The previous implementation
sampled `LapCurrentLapTime` whenever the lap counter grew, which stored
in-progress partial times and startup fragments.

Rules enforced by `DataProvider`:

- **Startup partial rejected** — the first observation after (re)connect only
  sets a baseline; laps completed before watching began are never recorded.
- **Duplicate sampling rejected** — repeated polls of the same lap number
  record nothing.
- **Invalid laps rejected** — zero, negative, and non-finite lap times are
  discarded.
- **Skipped transitions never fabricated** — if several laps complete between
  polls, only the most recently completed lap (`LapLastLapTime`) is recorded.
- **Resets** — history clears on session change (`SessionNum`), on reconnect,
  and on lap rollback (lap counter decreasing, e.g. a restart).
- **Capped** — the list keeps at most the last 10 laps.

## Roster (DriverInfo)

Driver names and car numbers now read the top-level `DriverInfo` SDK section,
which is how `irsdk` exposes it (`SessionInfo` only contains the `Sessions`
list). A compatibility fallback still supports payloads that nest `DriverInfo`
inside `SessionInfo`, and drivers without metadata fall back to generic
`Car <idx>` labels. The relative overlay keeps its existing car entry keys and
gains correct `name` / `car_number` values.

## Relative gaps are estimates

Relative gaps are derived from lap progress (`CarIdxLapCompleted` +
`CarIdxLapDistPct`) scaled by the player's best lap time. They are **not**
measured time intervals, and the payload now says so explicitly:

- each car entry carries `gap_is_estimate: true`;
- the `relative_data` object carries `gap_is_estimate: true`.

The UI prefixes estimated gaps with `~` (for example `~+2.35s`). The sign
convention is unchanged: positive gap means the car is **ahead** of the player,
negative means behind, and rows are coloured accordingly (`row-ahead` /
`row-behind`). Gaps are never taken from `CarIdxEstTime`, which cannot provide
precise intervals.

Additional accuracy rules:

- Cars with no valid track position (zero position, missing or non-finite lap
  distance) are rejected from the list.
- Progress differences are wrapped into a half-lap window with true modulo, so
  lapped cars (more than one lap apart) are compared by on-track proximity;
  `lap_delta` still reports the whole-lap difference.

## Radar track length

`radar_data` now includes `track_length_m`, derived from the actual
`WeekendInfo.TrackLength` string and its unit (`km`, `m`, or `miles`). When the
value is missing, unitless, or unparseable, `track_length_m` is `null` and the
radar UI shows proximity without meters — it never invents a length (the
previous build assumed a hardcoded 5500 m).

## Track map labelling

The track map overlay draws a **lap-progress ring**: cars are placed by lap
percentage around a circle, not on scaled track geometry. The visible overlay
label and the properties description now say so ("Lap Progress" /
"lap-progress ring … not scaled track geometry"). No geometry engine was added;
`name` and `display_name` in `properties.json` are unchanged so existing window
layouts keep matching.

## Non-finite and missing values

All shared `_safe_*` helpers reject `NaN`/`inf` and fall back to their
defaults, `_safe_int` no longer raises on `inf`, and the broadcast payload is
guaranteed strict-JSON safe for non-finite inputs (verified by
`json.dumps(..., allow_nan=False)` in the test suite). Missing SDK values
degrade to safe defaults instead of raising and dropping the whole payload.

## Front-end behaviour

- `relative.js` colours ahead/behind rows correctly and marks estimated gaps.
- `radar.js` uses `track_length_m` when present and omits meters otherwise.
- `laptime_graph.js` skips non-finite history points instead of drawing them.

## Test coverage

- `tests/test_telemetry_accuracy.py` — exercises the public
  `DataProvider.get_telemetry_data` with an injected fake SDK: connected,
  disconnected, and reset cases for every rule above, plus payload
  backwards-compatibility checks.
- `tests/test_accuracy_frontend.cjs` — runs the real overlay scripts against a
  stub DOM (Node built-in test runner, no dependencies) and checks rendering
  semantics and static overlay labelling.
