# Broadcast Driver Card

A compact lower-third card for the driver the **broadcast camera** follows
(ODD task T6, specs S1-S5). It is read-only: the overlay never sends commands to
the simulator. There is no automation: it does not switch the camera, change
the replay or write anything to the SDK.

```bash
python -m unittest discover -s tests -p "test_broadcast_driver.py"
node --test tests/test_broadcast_driver_frontend.cjs
```

## Routes and event

| Overlay               | Page                         | Socket.IO namespace | Event                     |
|-----------------------|------------------------------|---------------------|---------------------------|
| Broadcast Driver Card | `/overlay/broadcast_driver`  | `/broadcast_driver` | `broadcast_driver_update` |

The page is discovered automatically by the launcher and loads the shared theme
stylesheet after its own CSS. Original RAH and Glass
(`?theme=original|glass`, see `docs/overlay-themes.md`) show the same data. The
payload is also `broadcast_driver_data` on `DataProvider.get_telemetry_data()`
and is emitted only on its own event, never inside `telemetry_update`. A
missing payload (builder failure) reaches the overlay as "No data".

## Camera target vs. player

The card follows `CamCarIdx` only. `PlayerCarIdx` is never used as a fallback.

| `CamCarIdx` | Card |
|-------------|------|
| a car listed in `DriverInfo.Drivers`, or with a slot in the per-car arrays (index `0` is valid) | `available: true` for that car |
| missing, negative, boolean, non-integral (`1.5`), non-finite, text, or beyond every roster entry and array slot | `available: false`, `reason: "camera_unavailable"` |
| a pace car or spectator (`CarIsPaceCar` / `IsSpectator` in `DriverInfo`, the same filter the standings use) | `available: false`, `reason: "camera_target_excluded"` |

An unavailable card has every field `null` (`identity_available: false`). The
whole payload is rebuilt on each update and keeps no state, so a camera switch
never carries the previous driver's name or times over.

Your own speed, throttle, brake, clutch, steering, RPM, gear and fuel are
player-only SDK variables. They are **not read and not shown at all**, even when
the camera follows you, so the schema is the same for every camera target and
nothing of yours can appear as another driver's data. Per-car RPM and gear
(`CarIdxRPM`, `CarIdxGear`) are deliberately left out of this slice. Account
identifiers (`UserID`, team, iRating) are not published either.

## Payload

Variable names come from the pyirsdk variable list (`kutu/pyirsdk` `vars.txt`)
and the iRacing session YAML (`DriverInfo`). An unknown value is `null`; a real
`0` or `false` is kept. A name, class or rank is never invented (no `Car 2`).

| Key | Source | Meaning |
|-----|--------|---------|
| `available`, `reason` | `CamCarIdx` | see the table above; `reason` is `null` when available |
| `camera_car_idx` | `CamCarIdx` | validated integer, `null` when unavailable |
| `identity_available` | `DriverInfo.Drivers` | `false` when the camera car is not in the roster (roster absent or with holes) |
| `name`, `car_number`, `class_id`, `class_name` | `UserName`, `CarNumber`, `CarClassID`, `CarClassShortName` | text or `null`; `class_id` must be a non-negative integer |
| `position`, `class_position` | `CarIdxPosition`, `CarIdxClassPosition` | rank >= 1, else `null`; `class_position` also needs a known class |
| `laps_completed` | `CarIdxLapCompleted` | integer >= 0, else `null` |
| `last_lap_s`, `best_lap_s` | `CarIdxLastLapTime`, `CarIdxBestLapTime` (seconds) | positive finite seconds; the SDK's `-1`/`0` and `NaN` are `null` |
| `on_pit_road` | `CarIdxOnPitRoad` | real boolean, else `null` |
| `session_type` | `SessionInfo.Sessions[SessionNum].SessionType` | only when the session metadata confirms it; never a default |
| `source` | constant | `"CamCarIdx"` |

Private data the SDK does not expose per car (for example another driver's fuel
or inputs) is never inferred or estimated.

## Overlay behaviour

Name, number, class and session text are written with `textContent`, never HTML.
Numbers must be finite, ranks and laps whole. After 3 s without an update, on a
disconnect or connection error, or when the payload is `null`, the card is
cleared to `—`. Pit status is text ("IN PIT"), not only colour.

## Limitations and live validation

Everything above is covered by tests with a fake SDK and a stub DOM. No
simulator, desktop launcher or OBS session was used, so these still need
live validation:

- that `CamCarIdx` follows the broadcast/replay camera in your sessions and
  which value it reports when the camera is on no car;
- that `CarIdxPosition`, `CarIdxLastLapTime` and `CarIdxBestLapTime` are
  populated for other cars in the session types you use (they can be `0`/`-1`
  early in a session);
- how both themes look in the desktop launcher and as an OBS browser source.
  `backdrop-filter` blurs only content inside the page, never the game behind a
  transparent window, so Glass depends on its translucent fill.
