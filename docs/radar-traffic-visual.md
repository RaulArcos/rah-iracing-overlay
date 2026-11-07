# Radar longitudinal traffic

## Behavior and geometry

Radar uses the same DOM, data and layout in Original RAH and Glass. The native
window remains 320×210; the measured panel is 320×204. At 375 px viewport width
the widget retains its native width. No saved properties/default resolution change.

- White/gold **YOU** is the fixed own-car reference. Blue outlined car silhouettes
  represent valid nearby traffic. Every silhouette shares the same longitudinal
  axis: there are no inferred left/right lanes or per-car lateral coordinates.
- The clearly labelled plot covers **−100 to +100 m**, ahead above YOU, behind
  below. For signed distance `d = distance_pct × track_length_m`, marker centre
  `top = 50 − 0.4d` percent. Thus ±100 m maps to 10%/90%, leaving glyph clearance.
  Each telemetry update rebuilds current markers at the current coordinates;
  there is no decorative animation, interpolation or independent motion timer.
- Centres closer than 16 percentage points (about 18 px at native size) may share
  an outlined/count marker only on the **same signed side of YOU**. Cars are sorted
  by absolute distance, signed distance and index before grouping. The anchor is
  the **nearest member's actual longitudinal position**, independent of input order.
  Ahead, behind and exactly coincident rivals never collapse into one group.
  This intentionally sacrifices separation below the plot's visual resolution;
  it never jitters cars sideways or invents geometry to avoid overlaps. Exact
  zero/coincident distances are retained. YOU remains wider with a gold outline.
  Group labels include count/identities, with ellipsis for native-size legibility;
  the tooltip retains every member's identity and signed estimated meters.
- Actual SDK `DriverInfo.Drivers[].CarNumber` is labelled `#number` when present.
  Otherwise **IDX n** explicitly means SDK car index, not a fictional race number.
  Own index/is_player entries are excluded. Metadata uses `textContent`/`title`,
  never interpolated HTML.
- Supplied cars beyond ±100 m are counted as `N outside`, not clamped onto the
  plot boundary. The provider still limits its nearby payload to ±3.5% lap;
  the outside count only describes that supplied neighborhood, not the full field.
- Existing nearest ahead/behind numeric distances and fixed 100 m bars continue
  to update, including values outside plot range. Detailed source/percent notes
  and the legacy list remain accessible; the short visible legend and plot tooltip
  explain the schematic without a large footer.
- Left/right glows are generic `CarLeftRight` aggregate spotter warnings. No rival
  identity or per-car lateral position can be inferred from either or both glows.

## Source and validity

`CarIdxLapDistPct` supplies physical lap progress, validated finite and in [0,1]
**before** wrapping a difference into the nearest half-lap branch. `PlayerCarIdx`
must be an actual nonnegative integer (0 is valid); no missing index defaults to
zero and no negative index accesses the array tail. Explicit negative
`CarIdxTrackSurface` (NotInWorld) vetoes presence, including the player. Missing,
short or unknown surface arrays do not veto otherwise valid physical positions.
Lap counters/class ranks are not required: unknown counters in practice must not
remove physically observed cars. Integer lap differences do not affect proximity,
including lapped cars and start/finish crossings.

Meters derive only from the existing parsed `WeekendInfo.TrackLength`, with its
declared km/mi/m unit conversion. Missing/invalid length disables metric markers
and bars, states `length unavailable`, and keeps available percentage notes. No
5000 m fallback, synthetic flattening to zero, projected speed, or timing-derived
meters are used. The existing four-decimal `distance_pct` payload precision remains.

These are **lap-progress × track-length estimates**, not measured bumper gaps,
straight-line distances, world XY, heading or collision prediction. Curves, track
width and differing lines are not represented. A wrapped physical interval is
not a race timing gap or a lap-order comparison. Real live SDK accuracy remains
outside the fixture browser evidence below.

Null/malformed data, disconnect, connection error or >3 s silence removes all
traffic and clears warnings/bars. Unknown data never claims SAFE/CLEAR. A valid
empty neighborhood does not manufacture traffic or imply lateral safety.

## Verification (2026-11-07)

Test-first RED (before implementation):

- `python -m unittest discover -s tests -p test_radar_traffic.py`: exit 1,
  5 tests, 11 failing assertions/subtests (indices, presence, practice, coincidence).
- `node --test tests/test_proximity_frontend.cjs`: exit 1, 6 passed / 2 failed
  because no traffic glyphs were rendered.

GREEN:

- Backend focused: same command, 5 passed, exit 0.
- `node --test tests/test_proximity_frontend.cjs tests/test_accuracy_frontend.cjs`:
  17 passed, exit 0 (before the final overlap-threshold refinement).
- After final implementation/CSS changes,
  `python -m unittest discover -s tests`: **295 passed**, exit 0.
- `node --test tests/*.cjs`: **156 passed**, exit 0.
- `python tests/radar_traffic_browser.py`: **46 cases**, exit 0, no page errors;
  13 properties SHA-256 hashes preserved across browser verification.
- `git diff --check`: exit 0; existing repository LF/CRLF notices only.

Final correction: independent review reproduced opposite-side cars incorrectly
merging and changing placement when input order changed. A new Node regression
observed RED (8 pass / 1 fail), then GREEN (9/9) after deterministic signed-side
grouping. The full final Node suite passed **157 tests**. A targeted independent
OpenAI recheck also passed all 60 permutation/movement/grouping handler probes.
The updated Chromium harness passed **54 cases**, including ahead/rear separation,
reordered inputs and independent rear movement in both skins/native and narrow
viewports. An intermediate browser-fixture label mismatch was corrected to the
fixture's real `#44`; the position and movement assertions were retained.

The local Windows build completed successfully, running **295 Python tests** in
the isolated build environment. Parent launched the actual executable and passed
the full 26-PNG/demo/menu package check, plus explicit before/after Radar glyph
motion in both Original and Glass. The user closed their old RAH instance before
building; the check stopped only its own test process. No iRacing process was
stopped. Evidence: `.git/radar-traffic/build.log`, `node-final.log`, and
`package/radar-motion.json` with packaged screenshots.

Chromium uses installed Playwright and the existing read-only `preview_server`
public Flask routes on an ephemeral localhost port, never the user's app port.
Provider boundary fixtures are explicitly not a live SDK capture. Browser socket
handlers are injected only in the test page; production has no simulator/fake feed.
The final two cases run the actual existing opt-in `?demo=1` adapter/scenario,
unchanged, and assert automatically changing marker positions in both skins.

At each of 320×210 and 375×210 in both skins, browser assertions/screenshots cover:
two ahead/two behind, forward/rear motion, both generic side alerts, coincident
group, outside range, missing length, invalid/own IDs, literal hostile metadata,
null, disconnect, error and timed stale clearing. Reduced motion is enabled.
All state screenshots were visually reviewed through the four contact sheets;
both demo before/after pairs were also opened and reviewed.

Actual native marker evidence (same values both skins/viewport widths):

| Traffic | Signed meters before → after | top before → after | screen centre y before → after |
| --- | --- | --- | --- |
| #21 | +20 → +40 | 42% → 34% | 105.03125 → 96.078125 |
| #44 | −20 → −40 | 58% → 66% | 122.953125 → 131.90625 |
| #7 | +80 unchanged | 18% unchanged | 78.15625 unchanged |
| IDX 4 | −80 unchanged | 82% unchanged | 149.828125 unchanged |

Glyph centres stay x=160 px (the label container starts x=150). Coincident traffic
remains at top=50%, y=114 px. Clear states have zero `.traffic-car` elements.

Artifacts, private/local and intentionally outside public previews:

- `.git/radar-traffic/evidence.json`: per-state positions/status/panel bounds,
  demo before/after coordinates, provenance, all 13 property hashes.
- `.git/radar-traffic/{original,glass}-{320,375}-*.png`: individual state captures.
- `.git/radar-traffic/contact-{original,glass}-{320,375}.png`: reviewed contact sheets.
- `.git/radar-traffic/demo-{original,glass}-{before,after}.png`: automatic demo motion.

## Bounded changes and handoff

- `src/overlays/radar/radar.html`, `static/radar.css`, `static/radar.js`:
  visible car plot, honest range/legend, guarded telemetry movement/clearing.
- `src/data_provider.py`: only `_build_radar_data` presence/identity wiring changed
  in this slice. Other pre-existing dirty provider edits are preserved.
- `tests/test_radar_traffic.py`, `tests/test_proximity_frontend.cjs`,
  `tests/radar_traffic_browser.py`: public backend, actual JS and Chromium proof.
- `docs/radar-traffic-visual.md`: this behavior/provenance/evidence record.

Parent owns tracker completion, independent OpenAI review, public menu PNG refresh
and Windows build. This slice made no public PNG, demo scenario, shared appearance,
font, unrelated widget, saved-property, staging or commit changes.
