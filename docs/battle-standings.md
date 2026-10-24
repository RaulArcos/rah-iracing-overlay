# Battle & Pace and Multiclass Standings

Two read-only overlays built from real iRacing SDK per-car arrays (ODD task
T4, specs S1-S5). Neither sends commands to the simulator.

Run the regression suites with the standard runners only:

```bash
python -m unittest discover -s tests -p "test_battle_standings.py"
node --test tests/test_battle_standings_frontend.cjs
```

## Routes and events

| Overlay              | Page                    | Socket.IO namespace | Event                  |
|----------------------|-------------------------|---------------------|------------------------|
| Battle & Pace        | `/overlay/battle_pace`  | `/battle_pace`      | `battle_pace_update`   |
| Multiclass Standings | `/overlay/standings`    | `/standings`        | `standings_update`     |

Both pages follow the usual overlay layout, are discovered automatically by
the launcher and load the shared theme stylesheet after their own CSS. Original
RAH (default) and Glass (`?theme=glass`) render exactly the same data.

The payloads are also `battle_pace_data` and `standings_data` on
`DataProvider.get_telemetry_data()`. They are emitted only on their own event,
never inside `telemetry_update`, and each emit is isolated so one failing
overlay never blocks another. When a payload cannot be built the event carries
no data and the overlay shows "No data". Unknown values are `null`, never a
made-up zero; a real zero (`interval_s` of `0`, `laps_completed` of `0`) stays
`0`.

## SDK sources

From the pyirsdk variable list: `CarIdxPosition`, `CarIdxClassPosition`,
`CarIdxLapCompleted`, `CarIdxLapDistPct`, `CarIdxLastLapTime`,
`CarIdxBestLapTime`, `CarIdxF2Time` ("race time behind leader or fastest lap
time otherwise", seconds), `CarIdxOnPitRoad` and `PlayerCarIdx`.
`CarIdxEstTime` is the time to reach the car's current track location, not a
race gap, so it is never used here (the Relative overlay's progress-based gap
is a separate, labelled estimate).

Driver identity and class come from the top-level `DriverInfo.Drivers` section
(a `SessionInfo.DriverInfo` fallback exists): `CarIdx`, `UserName`,
`CarNumber`, `CarClassID`, `CarClassShortName`, `CarIsPaceCar`, `IsSpectator`.
The names follow the published session-info model of the IRSDKSharper library;
none were assumed. Pace cars and spectators are left out. A driver missing from
the section keeps `null` name, number and class: unlike the Relative overlay,
no "Car N" identity is invented.

Per-car arrays can be shorter than the car list, hold `-1`/`0` sentinels or
NaN; each read is bounds-checked (index `0` is a valid car, a negative or
out-of-range `PlayerCarIdx` never wraps to another car) and invalid values
become `null`. Lap times must be finite and positive.

## Standings payload

`classes` lists each class group, the class whose best car ranks highest
first, and unknown last. Cars are ordered by class position (practice and
qualifying without any rank: by best lap).

| Key | Unit / type | Meaning |
|-----|-------------|---------|
| `session_type` | string | `SessionInfo` type for the current `SessionNum`, `null` if unknown |
| `gap_basis` | string | `race_f2time` when race timing is usable (below), else `null` |
| `player_car_idx` | int | the listed player car, else `null` |
| `classes[].class_id`, `class_name`, `known` | int, string, bool | `CarClassID`, `CarClassShortName`; `known` is `false` for the single unknown-class group |
| `cars[].position`, `class_position` | int | `CarIdxPosition`, `CarIdxClassPosition`; `0` (not ranked) -> `null` |
| `cars[].car_number`, `name`, `laps_completed`, `on_pit_road`, `is_player` | | identity, `CarIdxLapCompleted`, `CarIdxOnPitRoad` (`null` if unknown) |
| `cars[].best_lap_s`, `last_lap_s` | seconds | `CarIdxBestLapTime`, `CarIdxLastLapTime` |
| `cars[].best_lap_delta_s` | seconds | best lap minus the fastest best lap of the same known class, `>= 0` |
| `cars[].gap_to_leader_s` | seconds | race only: seconds behind the **overall** leader; `0` for the leader |
| `cars[].laps_down` | laps | race only: whole laps behind the overall leader |
| `cars[].interval_s` | seconds | race only: `CarIdxF2Time` difference to the previous car in the class list when the pair is less than one lap apart; `>= 0` (see below) |

### Class handling

Cars are grouped by `CarClassID` only. A car without class metadata goes to an
explicit **unknown class** group ordered by overall position, with `null` class
position, interval and best-lap delta: rank collisions between classes are
never used to guess classes, and a class rank is meaningless once the class is
unknown.

### Race timing and lapped cars

`CarIdxF2Time` is only read as a race gap when `SessionInfo` says the current
session is a **Race** and `SessionState` is racing or checkered; with missing
metadata the gap stays `null` (the legacy "default to Race" is not used). In
practice, qualifying and warm-up `CarIdxF2Time` is a fastest lap and is
ignored, so gaps, `laps_down` and intervals are `null`.

`laps_down` compares race progress (`CarIdxLapCompleted + CarIdxLapDistPct`)
with the leader's, with no modulo wrap, so lapped cars never show a huge
negative time. A car less than one lap down gets its `CarIdxF2Time` as
`gap_to_leader_s`; a lapped car gets `laps_down` and no `gap_to_leader_s`,
because its time is not a plain gap to the overall leader. A non-leader
`CarIdxF2Time` that is zero, negative or not finite is unknown. With no car in
position 1 there are no gaps.

Intervals (and the battle `gap_s`) are pair timing, decided independently of
`gap_to_leader_s`, `laps_down` and the overall leader's position on track. Two
cars compare their `CarIdxF2Time` values only when both have valid race times
and the pair's own progress difference
`(ahead CarIdxLapCompleted + CarIdxLapDistPct) - (behind ...)` is at least `0`
and **less than one lap**. Whole-lap deficits to the overall leader are not the
test (two cars on different sides of the start line can have different
`laps_down` yet be a few hundred metres apart), and neither is class rank. So
two cars of a slower class that the overall leader has lapped get a real
interval to each other wherever the leader is, while a pair a full lap or more
apart, a pair with a missing or invalid time, a pair with unknown progress, or
a pair whose class order contradicts their progress (negative difference) gets
`null`. Race-metadata guards still apply: with no confirmed race there is no
pair timing. The pair interval relies on both cars' `CarIdxF2Time` being
measured against the same reference, which is part of the live validation
below. `CarIdxEstTime` is never used.

## Battle & Pace payload

The player's **same-class** neighbours by class position (`ahead` is
`class_position - 1`, `behind` is `class_position + 1`).

| Key | Meaning |
|-----|---------|
| `context` | `ok`; `class_unknown` (no class metadata: no same-class comparison is made); `class_position_unavailable`; `player_unavailable` |
| `class_id`, `class_name`, `session_type`, `gap_basis` | as in the standings |
| `lap_time_source` | `CarIdxLastLapTime/CarIdxBestLapTime`, used for the player and opponents alike |
| `player`, `ahead`, `behind` | car entry or `null` (no such car, or ambiguous duplicate class positions) |

A car entry has `car_idx`, `name`, `car_number`, `position`, `class_position`,
`laps_completed`, `last_lap_s`, `best_lap_s`, `on_pit_road`, `laps_down` and
`pace`. `ahead` and `behind` add:

| Key | Unit | Sign |
|-----|------|------|
| `gap_s` | seconds | always `>= 0`: how far that car is from the player; race timing only, `null` when either car is untimed or the pair is not less than one lap apart by its own progress (see Race timing); cars lapped by the overall leader still get a gap to each other |
| `last_lap_delta_s`, `best_lap_delta_s` | seconds | opponent minus player; negative means the opponent is faster |
| `pace_delta_s` | seconds | opponent minus player mean over the laps both have observed (at least two); negative means the opponent is faster |

### Pace and trend sampling

`pace` is built from **observed consecutive completed laps** of each car,
using `CarIdxLapCompleted` with `CarIdxLastLapTime`; the player is sampled the
same way and independently of the lap graph and fuel sampler. A lap is kept
only when the counter rose by exactly one since the previous poll and the car
was not on pit road at any poll of that lap. The first observation, a skipped
poll, a rollback, a pit lap or an invalid lap time never produce a sample (they
end the consecutive run), and repeated polls of the same lap add nothing. The
last five laps are kept. The state resets on a session change, on reconnect and
on a lap rollback.

`pace` holds `laps` (observed count), `avg_lap_s` (from two laps), and
`trend_s_per_lap` with `trend` (from three laps): the least-squares slope of the
lap times, `improving` at -0.05 s/lap or below, `worsening` at +0.05 or above,
otherwise `steady`. It is a small trend indicator, not a prediction.

The overlay colours a delta only when it is a real number (faster opponent:
warn, slower: ok, equal or unknown: neutral), so missing data never looks like
an advantage.

## Overlay behaviour

All metadata is rendered with `textContent`, never HTML. Standings show at
most eight cars per class (the top cars plus the player and neighbours). The
status chip reports waiting, live, no cars, no data, stale or disconnected.
After 3 s without an update, or on a disconnect / connection error, the values
are cleared instead of left stale.

## Limitations and live validation

Everything above is covered by tests against a fake SDK and a stub DOM. These
points still need live validation in a real session (no simulator was used):

- that `CarIdxF2Time` behaves as documented in a real multiclass race
  (including right after a restart and for cars in the pits);
- that `CarIdxLastLapTime` updates on the same poll as `CarIdxLapCompleted`;
- the `DriverInfo` class fields in your iRacing build, and that `CarClassID`
  is shared by every car of a class;
- that the interval between two cars of one class is a good measure when cars
  of other classes sit between them, and that `CarIdxF2Time` of two cars both
  lapped by the overall leader differs by their true on-track time gap
  (and that a pair just under a lap apart still gives a sensible interval);
- how both themes look in the desktop launcher and as an OBS browser source.
