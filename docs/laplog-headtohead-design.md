# Laptime Log and Head to Head (R3)

## Routes and visual contract

- `/overlay/laptime_graph?theme=original|glass`, event `laptime_graph_update`.
- `/overlay/battle_pace?theme=original|glass`, event `battle_pace_update`.
- Both opt into the existing `.rah-race` system after `overlay-theme.css`.
  Original uses dark ruled surfaces and sharp edges; Glass shares the exact
  layout with translucent rounded surfaces. Fonts are offline system fonts.
- References 1/2 form one coherent log: best band, ruled graph, compact
  Lap / Time / + To best / Track °C / Inc. table. Reference 6 becomes three
  ahead/player/behind driver bars and two recent-lap comparison strips.
- The log's **default resolution height only** changes from 230 to 620 pixels
  (width 540). Position and DPI fields are unchanged. Battle stays 640×330.
  No saved user properties or Input Telemetry properties are changed by R3.

## Player completion observations

`DataProvider._update_lap_times` remains the sole player history boundary owner.
`LapObservations` in `src/lap_observations.py` receives its existing begin,
duplicate, completion and reset decisions; it does not detect laps itself.

`laptime_graph_data.records` is an additive array aligned with the existing
ten-value `history`. It appends only when the legacy history appends a positive,
finite `LapLastLapTime`, retaining that same rounded seconds value. Every record
contains:

| Field | Source and availability |
|---|---|
| `lap_number` | SDK `LapCompleted`, nonnegative integer, otherwise null. Never an array index or inferred `Lap - 1`. |
| `time_s` | SDK `LapLastLapTime`, seconds, rounded to milliseconds under the existing append rules. |
| `track_temp_c` | Finite numeric `TrackTempCrew` at the observed completion poll, Celsius; null if unavailable. Finite negative Celsius is legitimate. |
| `incident` | Whether `PlayerCarMyIncidentCount` increased during a fully observed lap: true / false / null. |
| `observation` | `observed` for consecutive boundaries, `unavailable` when polls skipped boundaries. |

The first startup partial lap has **unknown incidents**, even if its final
temperature is available. The completion poll's incident-count change belongs
to the closing lap, then the new lap is baselined. Missing/nonfinite/negative
counts, count rollback, or a missing/nonfinite lap-counter poll taint the lap:
it cannot subsequently be called incident-free. Counts are not penalties or
invalid-lap flags. `×` means an observed incident-count increase; `·` means no
observed increase across the fully observed lap; `--` means unknown. An incident
does not assert an invalid lap, and this feature does not exclude it from bests.

Skipped boundaries still append the legacy last-time value once. That record's
lap label, temperature and incident are null, explicitly unavailable; missed
laps cannot be recovered. Later temperature/count/time samples never backfill
unknown records. Invalid time at a boundary still advances the legacy detector
without appending; a delayed valid time on a duplicate poll is not recorded.
Records and incident state reset alongside history on session changes,
successful reconnects and lap rollbacks. No fuel sampling rules or legacy graph
payload fields change. A nonfinite `Lap` poll retains its legacy error handling
while additionally invalidating incident certainty.

## Bests, deltas and graph units

- The band shows the real SDK `LapBestLapTime` session best when positive and
  finite. If absent, it explicitly labels the minimum retained observed time
  **OBSERVED BEST**, not session best. With no source it shows `--`.
- The band's temperature comes only from a matching retained completion
  record. A best before observation, a skipped completion or one aged out of
  the ten-record window has unknown temperature, even if current weather is
  available. It never substitutes current track temperature.
- Table delta is lap seconds minus the band's best, signed to milliseconds.
  Matching best rows are purple; slower positive deltas are red. Missing times,
  temperatures and incident certainty render `--`, never invented zeroes.
- Graph shows the last ten observed entries, preserving `laptime-canvas` and
  the legacy `history` fallback. Missing values break the line and never enter
  the numeric range. Faster times are higher, the visible best is purple,
  improvement against the preceding plotted lap is green, slower is red, and
  true incidents get an additional `×`. Graph best refers to displayed laps,
  which can differ from the earlier SDK session best.
- Axis labels use positive `m:ss.mmm`; half-second-quantised bounds and a
  minimum two-second range prevent jitter/flat-line magnification. Real slow
  laps remain real data; null/NaN/negative sentinels cannot create outliers.
- Existing footer best is SDK seconds, last is `m:ss.mmm`, and current delta
  requires the existing SDK delta-valid flag. Footer delta is not table delta.

## Recent lap comparisons, not sectors

Battle entries add `recent_laps_s`, at most five real completed times copied
from the **existing guarded pace observations** (`CarIdxLapCompleted`,
`CarIdxLastLapTime`, `CarIdxOnPitRoad`). First sight, skipped boundaries,
rollback, invalid time, missing car and pit-road contamination retain their
existing baseline/reset behavior. No new sampler or future prediction exists.

Ahead/behind entries additionally expose `recent_deltas_s`: opponent minus
player seconds, oldest to latest, right-aligned by recency. An unmatched count
gets a null hole (`--`), not a fabricated time or zero. Negative red chips mean
the opponent was faster; positive green chips mean the player was faster.
These are recent observed laps paired by recency, **not identical race lap
numbers, simultaneous laps, sectors, track segments or forecasts**. Different
pace-run lengths and asynchronous line crossings can change the pairing.
Driver bars retain actual position/class position, driver name, last completed
time and confirmed race gap. Existing pace/best/trend IDs and outputs remain
updated in the DOM, but the compact redesign displays the requested last-time
bars and recent chips rather than the previous metric-column layout.

## States, security and verification

Both scripts clear dynamic data on disconnect, connection error, malformed
payload and local silence longer than three seconds. Unknown comparison context
never invents rivals. Text uses `textContent`; there is no HTML interpolation
of names, class metadata or lap values. Empty plots remain explicit empty plots.

Test-first evidence:

- Initial public-provider RED: 7 tests, 6 missing-field errors, exit 1.
- Initial actual-script Node RED: 4 tests, 4 failures, exit 1.
- Additional nonfinite-lap certainty regression: 11 tests, 1 failure, exit 1
  before the additive taint hook; then corrected without changing history rules.
- Focused GREEN: 11 Python / 6 Node, exits 0.
- Full GREEN: **270 Python / 142 Node, exits 0**, all `tests/test_*.py` and
  `tests/test_*.cjs`. No skipped tests. `git diff --check` exits 0.
- The first full-suite evidence wrapper hit a Windows cp1252 console-printing
  error after saving the passing Node log. Its stdout handling was fixed and
  Node alone rerun to retain an explicit exit 0. Python did not need a rerun.

Browser verification uses installed Python Playwright/Chromium, real
`WebInterface` Flask public routes through its test client, actual provider
fixture output and actual overlay/theme JS. Only socket delivery/timer control
is simulated. There is no listening server or dependency installation.
`.git/redesign/r3scratch/check_r3.py` runs 40 states: two overlays × two skins ×
native/375px × empty/populated/stale/disconnected/hostile. Final probe: **40
states, zero failures, exit 0**, no JS errors, no horizontal overflow or native
height overflow. All 24 empty/populated/stale screenshots were individually
opened and inspected. Initial fit failures were corrected with local CSS
specificity/spacing fixes, preserving shared R1/R2 styles.

Evidence lives only in `.git/redesign/r3scratch/`: `payload.json`,
`browser-results.json`, `{overlay}-{skin}-{width}-{empty|data|stale}.png`, and
full test logs. They are simulated fixtures, not live iRacing proof.

## Live checks and source limits

Live iRacing, OBS and pywebview were not available for verification. Before
claiming live accuracy, check the SDK `Lap` / `LapCompleted` / last-time ordering
at real line crossings; incident-count update latency at the boundary; reconnect
and session restart; missing telemetry and long polling gaps; and track
temperature at the completion poll. A delayed SDK count can only be attributed
to the lap in which it is observed; physical incident timing cannot be recovered.
Track temperature is the sample at the observed boundary, not a historical
simulator weather query or precise finish-line timestamp. Verify actual desktop
window sizing and OBS transparency in both skins. Parent owns tracker updates
and independent OpenAI review before R4.

## Exact R3 file manifest

- `src/lap_observations.py` — focused observation state and recency pairing.
- `src/data_provider.py` — small additive reset/boundary/payload hooks; R2
  `enrich_race_metadata` wiring is preserved.
- `src/overlays/laptime_graph/laptime_graph.html`
- `src/overlays/laptime_graph/static/laptime_graph.css`
- `src/overlays/laptime_graph/static/laptime_graph.js`
- `src/overlays/laptime_graph/properties.json` — default height only.
- `src/overlays/battle_pace/battle_pace.html`
- `src/overlays/battle_pace/static/battle_pace.css`
- `src/overlays/battle_pace/static/battle_pace.js`
- `tests/test_lap_observations.py` — 11 public-provider tests.
- `tests/test_laplog_frontend.cjs` — 6 actual-script tests.
- `tests/test_accuracy_frontend.cjs` — legitimate canvas `fillText` mock only;
  existing assertions are retained.
- `tests/test_themes.cjs` — R3 migration membership only.
- `docs/overlay-themes.md` — additive R3 membership note.
- `docs/laplog-headtohead-design.md` — this source/design/evidence contract.

Local-only scratch: `.git/redesign/r3scratch/check_r3.py`, `run_suites.py`,
provider/browser JSON, full-suite logs and screenshots. No tracker/README,
shared CSS, other overlay source, profile, dependency or user property edits
are part of R3. No staging, commits, publishing or agents were used.
