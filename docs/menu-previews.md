# Menu previews and local simulated demos

## Use

Select an overlay in the launcher. The existing preview panel shows a native PNG
and the caption **Simulated preview — not live telemetry**. Changing Original RAH
to Glass refreshes the selected image immediately. **Preview Demo** opens a new
browser tab with the selected theme pinned, for example:

```text
/overlay/input_telemetry?demo=1&theme=glass
```

Only exactly one `demo=1` query parameter enables simulation. Missing, empty,
unknown values (`demo=true`, `demo=01`, `demo=0`) and duplicate demo parameters
remain real-data pages. Unknown overlays return HTTP 404. Normal Open URL and
desktop launch buttons keep their real behavior and never load demo scripts.

The demo is exclusively a browser-local fictional race, not iRacing telemetry.
A fixed, always-visible toolbar labels the data **Simulated telemetry / not
iRacing** and provides Pause/Resume. No simulator is needed for demos or capture;
the application HTTP surface is still needed to serve local assets.

## Isolation and replay

`src/overlays/__init__.py` conditionally injects trusted local `demo_race.js`,
`demo_scenario.js` and `demo_adapter.js` after the Socket.IO library and before
DOMContentLoaded. The adapter replaces `io` before widgets initialize. Its local
`.on()`/`.connect()` adapter dispatches deterministic event payloads every 250 ms;
it constructs no websocket or polling transport, emits no socket events and never
changes server SDK data. No production demo module imports test fixtures.

One fictional nine-driver, three-class race supplies the player, camera card,
relative, standings, proximity and observed lap records. Ratings and metadata are
simulated, not official. A four-lap replay loops after 1,440 frames. The initial
300-frame warmup immediately fills the input graph. Some fields change at lap
boundaries instead of every frame. Pause freezes history and scenario progress;
unchanged updates keep widgets' stale-data guards from clearing paused data.

The browser API is `RAHDemo.pause()`, `.resume()`, `.step(count)` and `.seek(frame)`;
`.seek()` defaults to frame 300, replays history and pauses for capture. `.tick`,
`.paused` and `.ready` expose capture state. Explicit demo/theme queries are not
saved to localStorage or copied into live URLs. The launcher's existing theme
selector still saves its normal theme preference; demos themselves write none.

## Assets: all 26 PNGs

Both links in each row are actual stored assets. Dimensions are pixels, identical
for both themes, read from the current properties without modifying them.

| Overlay folder | Original PNG | Glass PNG | Dimensions |
| --- | --- | --- | --- |
| battle_pace | [preview-original.png](../src/overlays/battle_pace/static/images/preview-original.png) | [preview-glass.png](../src/overlays/battle_pace/static/images/preview-glass.png) | 640 × 330 |
| blindspot | [preview-original.png](../src/overlays/blindspot/static/images/preview-original.png) | [preview-glass.png](../src/overlays/blindspot/static/images/preview-glass.png) | 380 × 120 |
| broadcast_driver | [preview-original.png](../src/overlays/broadcast_driver/static/images/preview-original.png) | [preview-glass.png](../src/overlays/broadcast_driver/static/images/preview-glass.png) | 620 × 250 |
| fuel_finish | [preview-original.png](../src/overlays/fuel_finish/static/images/preview-original.png) | [preview-glass.png](../src/overlays/fuel_finish/static/images/preview-glass.png) | 440 × 250 |
| input_telemetry | [preview-original.png](../src/overlays/input_telemetry/static/images/preview-original.png) | [preview-glass.png](../src/overlays/input_telemetry/static/images/preview-glass.png) | 640 × 160 |
| laptime_graph | [preview-original.png](../src/overlays/laptime_graph/static/images/preview-original.png) | [preview-glass.png](../src/overlays/laptime_graph/static/images/preview-glass.png) | 540 × 620 |
| pit_assistant | [preview-original.png](../src/overlays/pit_assistant/static/images/preview-original.png) | [preview-glass.png](../src/overlays/pit_assistant/static/images/preview-glass.png) | 560 × 300 |
| radar | [preview-original.png](../src/overlays/radar/static/images/preview-original.png) | [preview-glass.png](../src/overlays/radar/static/images/preview-glass.png) | 320 × 210 |
| relative | [preview-original.png](../src/overlays/relative/static/images/preview-original.png) | [preview-glass.png](../src/overlays/relative/static/images/preview-glass.png) | 480 × 340 |
| session_strip | [preview-original.png](../src/overlays/session_strip/static/images/preview-original.png) | [preview-glass.png](../src/overlays/session_strip/static/images/preview-glass.png) | 820 × 130 |
| standings | [preview-original.png](../src/overlays/standings/static/images/preview-original.png) | [preview-glass.png](../src/overlays/standings/static/images/preview-glass.png) | 660 × 560 |
| track_map | [preview-original.png](../src/overlays/track_map/static/images/preview-original.png) | [preview-glass.png](../src/overlays/track_map/static/images/preview-glass.png) | 360 × 360 |
| weather | [preview-original.png](../src/overlays/weather/static/images/preview-original.png) | [preview-glass.png](../src/overlays/weather/static/images/preview-glass.png) | 460 × 260 |

`/get_overlays` adds `preview_images` with `original`/`glass` URLs only for files
that exist. The existing `preview_gif` value and discovery behavior remain intact.
PNGs take precedence; missing/failed PNGs fall back to a legacy GIF, otherwise the
panel says no preview is available. Images load lazily with `object-fit: contain`
over a neutral surface. Preview title/description use textContent.

The existing `src/RAH_Telemetry_Overlay.spec` recursively collects `overlays`,
`interface` and `common`, so PNGs and runtime modules are bundled automatically.
Capture scripts and scratch evidence are development tooling, not runtime assets.

## Regeneration and browser smoke

Prerequisites: the project's Python/Flask environment, installed Python Playwright
and its installed Chromium browser. No new runtime dependencies are required.
If tooling is missing, a developer may separately provision it using
`python -m pip install playwright` and `python -m playwright install chromium`;
these installation commands were **not** run for this implementation.

```powershell
python scripts/generate_previews.py
python scripts/generate_previews.py --qa-only
```

The generator starts an isolated public-blueprint Flask server on an ephemeral
127.0.0.1 port, never port 8085 or the user's app. It imports no DataProvider/irsdk,
starts no Socket.IO server and rejects non-GET HTTP actions. Chromium uses its
own `.git/menu-previews/chromium-profile`, device scale 1, reduced motion and
`--disable-gpu`; external legacy launcher fonts/icons are blocked. No launch,
position or save routes are invoked. Source properties are SHA-256 checked before
and after. Scratch belongs exclusively to `.git/menu-previews`.

All 26 real DOM/canvas surfaces are rendered and PNG signatures/dimensions checked
before replacing public images (atomic replace per file). Native transparent
padding and Glass alpha are preserved; screenshots exclude the demo toolbar.
`--qa-only` validates stored assets without replacing them. Both modes check
all demos' animation/Pause/Resume, toolbar separation, 10 lap-log rows, three
standings classes/player highlight, all menu images/theme switches, the demo
popup, fallback and safe DOM handling. Requests, websocket openings, errors and
property hashes are recorded in `.git/menu-previews/browser-report.json`.

### Screenshot reproducibility

Replay data/layout are deterministic, but Chromium's composited input-pedal
surface showed tiny channel rounding even with GPU disabled. An earlier
`--qa-only` run completed all 26 demo checks and exited 1 at the former byte-exact
comparison. Comparing those captures with `scripts/preview_pixels.py`
passed: 25 images were exact; Input Glass differed in only 11 pixels within
x=325..352, y=47..142, by at most 3 RGBA channel levels. The comparator now permits only that
native pedal rectangle for Input Telemetry, maximum 3 levels, maximum 2,688 pixels;
everything elsewhere must match exactly. Different-theme negative control was
rejected. This is a narrowly bounded rendering tolerance, not a functional-test
tolerance. The parent subsequently reran the complete `--qa-only` command:
**exit 0, all 26 stored PNGs matched exactly in that run**. Independent OpenAI
review also confirmed those 26 decoded images were exact.

## Verification and screenshots

- RED: targeted Python and Node commands both exited 1 before implementation.
- GREEN: full `python -m unittest discover -s tests`: **275 passed, exit 0**;
  all `tests/test_*.cjs` through Node: **153 passed, exit 0**. Logs were reused
  rather than rerunning unchanged functional code after documentation/comparator work.
- Browser: 26 animated demos and 26 selected menu PNGs across both themes;
  zero Socket.IO requests, websocket openings, server write requests or page errors;
  demo localStorage and all 13 source property hashes unchanged. Glass alpha checked.
- Visual inspection covered all 26 stored assets at native resolution: meaningful
  input history, all ten plotted/logged laps, class/rating badges and highlighted
  player, both side warnings, distances, fuel, session and weather values.
- Evidence: `.git/menu-previews/{python-full.log,node-full.log,suite-exits.json,red-green.json}`.
- Screenshots: `.git/menu-previews/menu-<folder>-<theme>.png` and
  `demo-<folder>-<theme>.png`; six full-resolution contact sheets are
  `contact-original-1.png` through `contact-original-3.png` and
  `contact-glass-1.png` through `contact-glass-3.png` in the same directory.
- Independent OpenAI source, PNG and isolation review: **PASS**, including three
  focused Python tests, five focused Node tests and 117 normal/invalid/duplicate
  query responses byte-identical to ordinary template rendering.
- Windows executable/ZIP rebuilt successfully. The build environment ran all
  **275 Python tests successfully**. Parent launched the packaged application
  and drove all **26 animated demos, 26 menu selections and 26 bundled PNG URLs**
  in Chromium. No demo Socket.IO/WebSocket connections, server writes or property
  changes occurred. Evidence: `.git/menu-previews/package/report.json` and
  `.git/menu-previews/build.log`.

## Known limits / parent handoff

These images illustrate the existing native layouts, including their existing
responsive hiding and text ellipsis (for example long pit-service requests).
The lap-progress ring shows a close fictional pack, not track geometry. Missing
start-gain values deliberately remain `--`. Existing widget source labels/Live
badges are contextualized by the demo's permanent simulated toolbar and the menu
caption; screenshots are not evidence of official or live timing accuracy.
Cross-version/browser/font rasterization can differ and may require regeneration.
Live iRacing and OBS/desktop transparency remain separate manual checks. They are
not needed to use these explicitly simulated previews. The current local Windows
build includes the demo scripts and all PNGs; source remains uncommitted and no
release was uploaded.
