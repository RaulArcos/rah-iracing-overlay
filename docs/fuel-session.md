# Fuel & Finish and Session Strip

Two read-only, advisory overlays built from real iRacing SDK variables
(ODD task T3, specs S1-S5). Neither overlay sends commands to the simulator:
there is no automatic refuel, pit call or setup change.

Run the regression suites with the standard runners only:

```bash
python -m unittest discover -s tests -p "test_fuel_session.py"
node --test tests/test_fuel_session_frontend.cjs
```

## Routes and events

| Overlay        | Page                     | Socket.IO namespace | Event                 |
|----------------|--------------------------|---------------------|-----------------------|
| Fuel & Finish  | `/overlay/fuel_finish`   | `/fuel_finish`      | `fuel_finish_update`  |
| Session Strip  | `/overlay/session_strip` | `/session_strip`    | `session_strip_update`|

Both pages follow the usual overlay layout (`<name>.html`, `properties.json`,
`static/<name>.css|js`), are discovered automatically by the launcher, and load
the shared theme stylesheet after their own CSS. Both themes (Original RAH and
Glass, see `docs/overlay-themes.md`) render exactly the same data; the theme
only changes styling (`?theme=original|glass`). The Original look is the
default.

The payloads are also available as `fuel_finish_data` and `session_strip_data`
on `DataProvider.get_telemetry_data()`. They are emitted only on their own
event, never inside `telemetry_update`, whose normalization turns nested values
into `0.0`. When a payload is missing the event carries no data (the
overlay receives `undefined`/`null`) and the overlay shows "No data".

Unavailable values are `null`, never a made-up zero. A real zero (empty tank,
zero laps remaining, no flags) stays `0` / `[]`.

## Fuel & Finish payload

| Key | Unit / type | Meaning |
|-----|-------------|---------|
| `fuel_level_l` | liters | `FuelLevel` (the SDK reports liters); `null` when missing, negative or non-finite |
| `fuel_level_pct` | percent 0-100 | `FuelLevelPct` (SDK fraction) x 100; `null` outside 0-1 |
| `avg_burn_l_per_lap` | liters per lap | mean burn of the retained clean-lap samples; `null` without samples |
| `burn_sample_count` | int | samples behind the average (at most 10, rolling window) |
| `burn_source` | string | `observed_clean_laps` when there are samples, else `null` |
| `laps_of_fuel` | laps | `fuel_level_l / avg_burn_l_per_lap` |
| `finish_laps_remaining` | laps | laps still to run; see below |
| `finish_basis` | string | `laps_remaining` or `timed_conservative_estimate` |
| `finish_fuel_needed_l` | liters | `avg_burn x finish_laps_remaining` |
| `finish_fuel_to_add_l` | liters | `max(needed - fuel_level_l, 0)` |
| `is_estimate`, `advisory` | bool | always `true`: values are estimates, not instructions |

### How burn is sampled

Sampling reuses the existing completed-lap detector (`_update_lap_times`), so
the lap graph and the fuel samples can never disagree about lap boundaries.
A lap produces a sample only when all of this holds:

- the lap started and ended on **observed consecutive boundaries** (the
  startup partial lap and laps after skipped polls are never sampled);
- the lap time is valid (finite and positive);
- every poll of the lap had a valid, non-negative `FuelLevel`;
- no poll saw a **refuel**: the level is compared with its running minimum
  since the last refuel, so slow pit-flow refuelling is caught as well as
  jumps. A rise of more than 0.1 L above that minimum counts; smaller,
  non-accumulating jitter is tolerated;
- no poll had `OnPitRoad`, `PlayerCarInPitStall` or `IsReplayPlaying` set, or
  `IsOnTrack` false (fields absent from the SDK are ignored);
- the measured burn is positive.

Samples are discarded on a new session, reconnect, lap rollback and on any
refuel, so an old stint average cannot mislead a new stint. The lap-time
history of the Laptime Graph is unchanged by any of this.

### Finish estimate

- **Lap-limited sessions**: `SessionLapsRemainEx` is preferred, with
  `SessionLapsRemain` only as a fallback when the extended variable is absent.
  Values of 32000 and above (the SDK's "unlimited" sentinel), negative values
  and NaN are unavailable; a confirmed `0` is valid. The count is used as whole
  laps, so a lap in progress counts fully: mid-lap this can over-estimate by the
  distance already run (it never under-counts on that account).
- **Timed sessions**: the exact distance is unknowable. Only when `SessionInfo`
  establishes a time limit (`limit` is `time` or `laps_and_time`) and `SessionTimeRemain` is valid, the estimate is
  `time_remaining / fastest clean sampled lap + 1` laps. The fastest lap makes
  it conservative (more laps); the extra lap covers finishing the lap in
  progress after the clock. It is labelled `timed_conservative_estimate` and is
  never exact. It stays unavailable without a clean sampled lap, and whenever
  the session metadata is missing, unknown or unlimited.
- **Unlimited sessions** (and sessions where both metadata limits are
  unlimited) have no finish estimate.
- If a session has both a lap and a time limit, the lap count is used.

No safety margin is added; add your own.

## Session Strip payload

| Key | Meaning |
|-----|---------|
| `session_type` | `SessionInfo.Sessions[SessionNum].SessionType`; `null` when metadata is absent (never defaults to Race) |
| `limit` | `laps`, `time`, `laps_and_time`, `unlimited`, or `null` if metadata is incomplete |
| `session_laps_total`, `session_time_total_s` | metadata limits (seconds for time) |
| `laps_remaining`, `laps_remaining_source` | same rules as above; source is `SessionLapsRemainEx` or `SessionLapsRemain` |
| `time_remaining_s` | `SessionTimeRemain` in seconds; `null` for unlimited time, negative, non-finite or the 604800 s sentinel; `0` is valid |
| `state`, `state_code` | `SessionState` decoded with the installed `irsdk.SessionState` enum; unknown/invalid -> `null` |
| `flags` | `SessionFlags` bitmask decoded with the installed `irsdk.Flags` enum, in bit order; `[]` when no flag bit is set, `null` when unavailable; unknown bits are ignored |
| `position`, `class_position` | the player's `CarIdxPosition` / `CarIdxClassPosition`; `0` (unknown) -> `null` |
| `lap` | the player's `Lap` |

The overlay shows the highest-priority flag (red, black, checkered, yellow,
blue, white, green ...) and a status chip: waiting, live, no data, stale, or
disconnected. All metadata is rendered with `textContent`, never HTML. After
3 s without an update or on a disconnect / connection error the values are
cleared rather than left showing stale data.

## Limitations and live validation

Everything above is covered by tests against a fake SDK and a stub DOM. These
points still need live validation in a real session (no simulator was used):

- that `SessionLapsRemainEx` counts the lap in progress as assumed, and the
  32767 / 604800 s "unlimited" sentinels in your iRacing build;
- fuel sampling across a real pit stop, tow, reset and session change;
- the timed-race estimate against actual finishes (leader-finish rules can add
  a lap);
- how both themes look in the desktop launcher and as an OBS browser source.
  `backdrop-filter` blurs only content inside the page, never the game behind a
  transparent window, so Glass depends on its translucent fill.
