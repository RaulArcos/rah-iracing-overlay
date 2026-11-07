# Relative and Standings: R2 design and data contract

## Routes and implementation

- `/overlay/relative?theme=original` and `?theme=glass`; Socket.IO namespace
  `/relative`, event `relative_update`.
- `/overlay/standings?theme=original` and `?theme=glass`; namespace `/standings`,
  event `standings_update`.
- Local `race-system.css` is opt-in through `.rah-race`, loaded after
  `overlay-theme.css`. Original and Glass share all structure, data and sizing.
  No external assets, fonts, network lookups, dependencies or fake branding.
- `src/race_metadata.py` enriches the completed public telemetry result once per
  poll. `data_provider.py` has only an import and one call added. Existing gap
  calculation, timing guards, lap resets/sampling and event routing are unchanged.
- Local `common/js/race_metadata.js` is genuinely shared: guarded badges, colors,
  SoF labels and session summary formatting. All metadata is rendered with
  `textContent`; colors must match a validated six-digit RGB form.

## Visual anatomy

References `.git/redesign/refs/7.png` and `8.png` were viewed. The layouts use
their dense broadcast hierarchy, without copying assets: gold column labels,
white position boxes, colored class strips/number blocks, aligned timing columns,
white iRating badges, license/SR badges, and an amber actual-player row.

Relative keeps the twelve-opponent legacy payload unchanged and adds a separate
`player` object. It displays six nearest opponents plus the actual player,
ordered by signed on-track gap. Without a confirmed player it displays at most
seven opponents and never highlights an invented player. The gap remains
shown with one decimal and no `~` marker; the player's zero is a self-reference,
not a measured race interval. SDK track-time profiles now replace the old uniform
distance-times-lap estimate; missing timing stays unavailable. See
[relative-ai-fix.md](relative-ai-fix.md) for the current timing and AI-session
profile rules. Native size remains 480x340, with the same columns at 375px.

Standings retains existing class grouping and selection (top cars plus player
and neighbors, maximum eight rows per class). Each class strip shows its SoF.
White boxes show class position; overall position stays alongside. Colored
number blocks use the real SDK class color. Last lap, overall gap and class
interval remain aligned; lap count and PIT are retained. Best-lap values remain
in the payload and legacy DOM cells, but are hidden in the compact visual layout.
At 375px each row reflows into two compact lines with timing labels aligned in
the column header. Native size remains 660x560. Long rosters or arbitrary-length
metadata can use the bounded list's vertical scrollbar; no horizontal cropping
or window/settings changes are required.

## SDK provenance and availability

Confirmed against the published session YAML model:
[IRSDKSharper IRacingSdkSessionInfo.cs](https://github.com/mherbold/IRSDKSharper/blob/main/IRacingSdkSessionInfo.cs).
Its `DriverInfoModel.DriverModel` declares `IRating`, `LicString`, `LicSubLevel`,
`LicColor`, `CarClassColor`, `CarIdx`, `CarClassID`, `CarClassShortName`,
`CarIsPaceCar`, and `IsSpectator`. The driver section is read at top level;
the existing nested SessionInfo fallback is retained. No runtime web request is
made. SDK field/type confirmation is not a claim of live-simulator validation.

Both widgets receive the same additive per-car fields:

| Field | Unit/source | Null / validation rule |
| --- | --- | --- |
| `irating` | rating points, `DriverInfo.Drivers[].IRating` | Only positive integral finite numbers; zero/negative/boolean/text/NaN/infinity are unavailable. UI rounds to one decimal in thousands; exact value in badge tooltip. No predicted iRating gain. |
| `license` | class from `LicString` | Only recognized R/D/C/B/A/P/Pro/WC forms, optionally followed by the SDK SR text; unknown/hostile text is null. |
| `safety_rating` | `LicSubLevel / 100` | Requires recognized license and integral sublevel 1..499. No fallback from invalid data or a made-up default. |
| `license_color` | RGB from `LicColor` | SDK `0xRRGGBB`, `#RRGGBB` or numeric 24-bit YAML values normalized to `#rrggbb`; otherwise null. A neutral surface is used when unavailable. |
| `class_color` | RGB from `CarClassColor` | Same validation. A class strip uses the color only if its roster has one consistent known color. |
| `positions_gained` | overall places gained from confirmed actual race start | **Currently null**: no unambiguous actual starting-position source was confirmed. |
| `positions_gained_source` | source identifier | Null with unavailable gains. Frontend will not show a gain without a source. |

### Position-gain limitation

The confirmed session model's `ResultsPositions` is current classified results;
`QualifyPositions` and `QualifyResultsInfo.Results` are qualifying classification.
Those do not, by themselves, establish an actual race starting position for
custom/reversed grids, heats or pit starts. Neither is substituted for a start.
Practice and race both keep gains null, even when these result sections exist.
The UI reserves `±P` and displays `--`. Providing non-null gains requires a
separately confirmed actual-start source; no tracking snapshot or qualifying-rank
guess has been added in this slice.

### Class strength of field

Each Standings class receives `sof: {value, rated, total, complete}`. Relative
receives the identical player's class result as `player_class_sof`.

For positive real ratings `r[i]`, the derived sample SoF is:

```text
SoF = round(-1600 / ln(2) * ln(sum(exp(-r[i] * ln(2) / 1600)) / n))
```

The implementation uses the minimum-rating-shifted equivalent to avoid numeric
underflow. It is not a server-provided official race SoF. The sample is the
current unique-CarIdx DriverInfo roster of that confirmed class, excluding pace
cars and spectators; it includes entrants not currently ranked. `rated` counts
valid ratings; `total` counts those known class entrants. Missing ratings are
excluded from the formula and `complete=false` labels the result
`SoF N · partial rated/total`. No valid ratings means `value=null`, displayed as
`SoF --`. Unknown-class cars never get a mixed-class SoF. Completeness describes
the known roster only, not proof that every real race entrant was supplied.

### Session summary

Both payloads add the same `session_summary`:

- `session_type`, `lap`, `lap_limit`, `time_limit_s`: existing validated
  Session Strip values, sourced from current `SessionInfo`/`SessionNum`, `Lap`,
  `SessionLaps`, `SessionTime` metadata. Limits remain null for unlimited/unknown.
- `elapsed_s`: finite nonnegative numeric SDK `SessionTime`, seconds.
- `track_temp_c`: finite numeric `TrackTempCrew`, degrees Celsius; never a
  per-lap observation or a forecast. Relative shows the rounded track temperature.
- `field_size`: count of unique non-pace/non-spectator DriverInfo entries;
  null when there is no roster. Relative shows this count.

The footer formats elapsed/limit as minutes:seconds and lap/limit without
inventing unknown totals. Standings' existing gap remains seconds behind the
overall race leader, or laps down when lapped; interval remains to the preceding
same-class car and only when existing race timing guards permit it. Practice
and unconfirmed race timing remain unavailable. Relative's sign and estimate
labels are unchanged: positive ahead, negative behind.

In AI sessions, explicit `CarIsAI` opponents have AI badges rather than account
ratings. The observed player placeholder `IRating=1 / R 0.01` is not displayed as
a real account profile; unavailable values stay `--`. AI sessions have no numeric
class SoF. See the correction notes linked above for the narrow placeholder guard.

## Missing, stale and hostile data

Missing/invalid values display `--`; no zero rating, synthetic opponent, rating
gain or race-time gap is fabricated. Both scripts clear on disconnect,
`connect_error`, invalid payload, or more than three seconds without an update.
An empty telemetry poll causes server-wide silence. On a nonempty poll missing
the widget sections, Relative receives its legacy empty-car default and Standings
receives null. The stale timer also handles silence. The pre-existing legacy
Relative server disconnect-callback signature is outside this metadata/layout
slice; socket integration tests follow the existing legacy test-client teardown
convention and browser tests explicitly invoke client-side disconnect handlers.

Names, numbers, class names, license text and session metadata cannot create
markup. Hostile long strings remain literal text and may require vertical list
scrolling rather than being silently truncated.

## Verification and handoff

Test-first evidence, commands and screenshots are recorded in the R2 handoff.
The new Python regression file exercises public `get_telemetry_data`, HTTP
routes/assets and Socket.IO events. Existing accuracy DOM tests were adapted
from interpolated HTML strings to equivalent actual-node class/text assertions;
their sign, estimate and pit checks remain. Existing Standings identity/timing,
selection, XSS, stale and theme assertions remain, plus new badge/SoF/Relative
player and CSS-color guard coverage through the real scripts.

The isolated installed-Python-Playwright probe is
`.git/redesign/r2/check_r2.py`. It intercepts real Flask test-client routes at
`http://rah.test`, loads actual templates/scripts/styles and injects public
provider payloads into Socket.IO callbacks. No HTTP listener, port 8085, simulator,
external network, installations or saved settings are used. Evidence lives only
under `.git/redesign/r2/`: `payload.json`, `browser-results.json`, and PNGs named
`{relative|standings}-{original|glass}-{native_width|375}-{data|empty|hostile}.png`.

Normal populated and empty layouts are checked for panel/text bounds,
horizontal overflow, native viewport height, list overflow and JavaScript or
console errors. Populated screenshots contain three classes/eight real fixture
entrants, one actual player and seven Relative rows. Stale and disconnected
states must clear the player row. Hostile fixtures must not create an image or
execute markup; arbitrary-length hostile text may scroll vertically. The 16
populated/empty native/375px screenshots were individually viewed. Browser proof
is simulated fixture proof, not live iRacing/OBS/desktop transparency validation.

Tracker ownership remains with the parent; R3/R4 are separate slices.

### Recorded results

| Check | Observed result |
| --- | --- |
| Backend RED, before enrichment | `python -m unittest discover -s tests -p test_relative_standings_metadata.py`: 6 tests, 12 missing-field errors, exit 1. |
| Initial backend GREEN | Same command: 6 tests, exit 0. Expanded final coverage: 10 tests, exit 0. |
| Frontend RED | `node --test tests/test_battle_standings_frontend.cjs`: 24 tests, 21 pass / 3 fail, exit 1, before new UI implementation. |
| Focused final GREEN | Accuracy + Battle/Standings real-script tests: 34 tests, 34 pass, exit 0. |
| Full Python GREEN | `python -m unittest discover -s tests -q`: 259 tests, OK, process exit 0. |
| Full Node GREEN | All `tests/test_*.cjs` passed: 136 tests, 136 pass, 0 fail / 0 skipped, process exit 0. |
| Browser final GREEN | `python .git/redesign/r2/check_r2.py`: 40 states, 0 failures, exit 0. Native Relative 480x340 / Standings 660x560 and 375px at the same heights, both themes. |

The first full pass exposed an intentional TrackTempCrew contract expansion and
old Node fixtures missing the shared helper / migration boundary updates. These
were adapted without removing their regressions. Final complete output is in
`full-python.log` and `full-node.log`. The scratch log recorder itself hit a
Windows cp1252 console error printing the Node summary **after both test
processes exited 0 and the logs were saved**; its summary printing was made
ASCII-safe. The saved Node log confirms all 136 tests passed.

R2 production/test/document files edited (other dirty worktree files predate R2):

```text
src/data_provider.py
src/race_metadata.py
src/common/css/race-system.css
src/common/js/race_metadata.js
src/overlays/relative/relative.html
src/overlays/relative/static/relative.css
src/overlays/relative/static/relative.js
src/overlays/standings/standings.html
src/overlays/standings/static/standings.css
src/overlays/standings/static/standings.js
tests/test_relative_standings_metadata.py
tests/test_accuracy_frontend.cjs
tests/test_battle_standings_frontend.cjs
tests/test_pit_weather.py
tests/test_suite_integration.cjs
tests/test_themes.cjs
docs/relative-standings-design.md
```

The R1 rules in `race-system.css` remain intact (three badge-rule lines added).
The parent's theme test keeps both existing R1 assertions and updates only its
migrated/unmigrated membership for R2. No tracker, properties, generated build or
dist outputs were edited by R2. Scratch probe/log files are confined to
`.git/redesign/r2/`. No staging, commits, publishing or model/agent changes.
