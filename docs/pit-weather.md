# Pit Assistant and Weather

Two read-only overlays built from real iRacing SDK variables (ODD task T5,
specs S1-S5). They only observe: the overlays never send commands to the
simulator. There is no automation: no pit call, no automatic refuel, no limiter
control, no setup change, and no weather forecast.

Run the regression suites with the standard runners only:

```bash
python -m unittest discover -s tests -p "test_pit_weather.py"
node --test tests/test_pit_weather_frontend.cjs
```

## Routes and events

| Overlay       | Page                     | Socket.IO namespace | Event                  |
|---------------|--------------------------|---------------------|------------------------|
| Pit Assistant | `/overlay/pit_assistant` | `/pit_assistant`    | `pit_assistant_update` |
| Weather       | `/overlay/weather`       | `/weather`          | `weather_update`       |

Both pages follow the usual overlay layout, are discovered automatically by the
launcher and load the shared theme stylesheet after their own CSS. Original RAH
and Glass (`?theme=original|glass`, see `docs/overlay-themes.md`) render the
same data; only the styling differs. The payloads are also available as
`pit_assistant_data` and `weather_data` on `DataProvider.get_telemetry_data()`
and are emitted only on their own event, never inside `telemetry_update`. A
missing payload reaches the overlay as no data ("No data").

Unavailable values are `null`, shown as `—`. A real zero (`0.0` seconds,
`0 m/s` wind, `0 %` rain) or `false` is kept. Numbers must be finite numerics:
negative durations, `NaN`/`inf`, text and booleans-as-numbers are `null`, and so
are flags that are not real booleans (such as `1` or `"yes"`).

## Pit Assistant payload

Variable names and units come from the pyirsdk variable list
(`kutu/pyirsdk` `vars.txt`).

| Key | Source | Meaning |
|-----|--------|---------|
| `speed_kmh` | `Speed` (m/s) x 3.6 | `null` if missing, negative or non-finite |
| `on_pit_road`, `in_pit_stall`, `pits_open`, `service_active` | `OnPitRoad`, `PlayerCarInPitStall`, `PitsOpen`, `PitstopActive` | real booleans, otherwise `null` |
| `pit_speed_limit_kmh`, `pit_speed_limit_source` | `WeekendInfo.TrackPitSpeedLimit` | see below |
| `pit_speed_margin_kmh`, `pit_speed_state` | limit minus speed | `within_limit` / `over_limit`; `null` unless on pit road with a valid speed and a known limit |
| `repair_left_s`, `optional_repair_left_s`, `tow_time_s` | `PitRepairLeft`, `PitOptRepairLeft` (s), `PlayerCarTowTime` (s) | seconds; `0` is real |
| `service_flags`, `service_flags_raw` | `PitSvFlags` bitfield | names of the bits the installed `irsdk.PitSvFlags` enum knows (`lf_tire_change`, `fuel_fill`, ...) in bit order, plus the raw integer so unknown bits stay visible |
| `service_status`, `service_status_code` | `PlayerCarPitSvStatus` | name from the installed `irsdk.PitSvStatus` enum; unknown code keeps the code and a `null` name |
| `service_fuel_amount`, `service_fuel_unit`, `service_fuel_requested` | `PitSvFuel`, `PitSvFlags` | see below |

### Pit speed limit

`WeekendInfo.TrackPitSpeedLimit` is typed as a string in the published
IRSDKSharper session model (`IRacingSdkSessionInfo.cs`) and normally reads like
`"60.00 kph"`. A value is used only when it states its unit (`kph`, `km/h`,
`mph` or `m/s`) and is converted to km/h. A unitless, negative, zero, malformed
or non-string value is "no limit" and nothing is guessed. The margin is
`limit - speed` and the state is `over_limit` below zero; the overlay does not
read `dcPitSpeedLimiterToggle` (an in-car control toggle), so no limiter on/off
state is shown. Margin and state exist
only while `OnPitRoad` is true, because the limit does not apply elsewhere.

### Pit service fuel

`PitSvFuel` is "l or kWh" in the SDK list and the SDK does not say which applies,
so the overlay shows the amount with the label `L/kWh` and never claims liters.
It is the amount the pit menu **asks for**, not fuel added. The overlay shows it
only when the `fuel_fill` bit of `PitSvFlags` is set (`NOT REQUESTED` when the
bit is clear). It is not connected to the fuel finish estimate of
`docs/fuel-session.md`, which stays a separate advisory calculation.

## Weather payload

All values are what the SDK reports now: observed conditions, not a forecast. Air temperature, humidity, wind and
precipitation are measured at the start/finish line; track temperature is
measured by the crew around the track.

| Key | Source | Meaning |
|-----|--------|---------|
| `air_temp_c`, `track_temp_c` | `AirTemp`, `TrackTempCrew` (Celsius) | negative values are valid; the deprecated `TrackTemp` is not read |
| `humidity_pct` | `RelativeHumidity` | SDK 0..1 ratio x 100 |
| `precipitation_pct` | `Precipitation` | SDK 0..1 ratio x 100; observed precipitation now, not a rain probability |
| `wind_speed_ms`, `wind_speed_kmh` | `WindVel` (m/s) | non-negative |
| `wind_dir_deg` | `WindDir` (rad) | normalised to `[0, 360)` degrees; the overlay does not say whether it is the direction the wind comes from or goes to |
| `track_wetness`, `track_wetness_code` | `TrackWetness` | name from the installed `irsdk.TrackWetness` enum (including the SDK's own `unknown`); an unlisted code keeps the code and a `null` name |
| `declared_wet` | `WeatherDeclaredWet` | the steward's "rain tires allowed" declaration |
| `observed` | constant | always `true`: observation only |

Humidity and precipitation are published with the unit `%` but use 0..1 values,
like the other fraction variables of the SDK. A value outside 0..1 is `null`; it
is never rescaled.

Nothing is defaulted: a missing variable is `null`, not "dry", "calm" or
"sunny". There is no trend, prediction or rain probability.

## Overlay behaviour

Status chips carry text ("OVER LIMIT", "CLOSED", "YES"), not only colour. All
payload text is written with `textContent`, never HTML. After 3 s without an
update, or on a disconnect or connection error, values are cleared to `—`
rather than left stale.

## Limitations and live validation

Everything above is covered by tests with a fake SDK and a stub DOM. No
simulator, desktop launcher or OBS session was used, so these still need
live validation:

- that your tracks report `TrackPitSpeedLimit` with a unit string, and how the
  margin behaves at the pit entry and exit cones;
- the `PitSvFlags` / `PlayerCarPitSvStatus` values seen during a real stop,
  including electric cars where `PitSvFuel` is kWh;
- the real range of `Precipitation`, `TrackWetness` and `WindDir` (including
  its compass convention) in dynamic-weather sessions;
- how both themes look in the desktop launcher and as an OBS browser source.
  `backdrop-filter` blurs only content inside the page, never the game behind a
  transparent window, so Glass depends on its translucent fill.
