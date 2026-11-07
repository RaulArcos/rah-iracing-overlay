# Visual redesign: delivery and validation

## Run the redesigned application

The current Windows build is at
`dist/RAH_Telemetry_Overlay/RAH_Telemetry_Overlay.exe`. Keep the entire application
folder, including `_internal`; the executable is not a standalone one-file bundle.
The shareable archive is
`release/RAH_Telemetry_Overlay-20261106-c13f259.zip`.

This is a local working-tree build. The filename's revision identifies the last
commit, not a claim that these redesign changes have been committed or published.
To rebuild from current source, double-click `build.bat`.

Select Original or Glass in the launcher, or pin it in an OBS/browser URL:

```text
http://127.0.0.1:8085/overlay/relative?theme=original
http://127.0.0.1:8085/overlay/standings?theme=glass
http://127.0.0.1:8085/overlay/laptime_graph?theme=glass
http://127.0.0.1:8085/overlay/battle_pace?theme=original
http://127.0.0.1:8085/overlay/radar?theme=glass
http://127.0.0.1:8085/overlay/blindspot?theme=original
```

Without iRacing, widgets wait for telemetry; screenshots containing cars and lap
data below were produced with explicitly simulated fixtures.

## Shipped source changes

- All 13 overlays share red title strips, consistent typography, tabular numbers
  and semantic status colours. Original is dark/sharp; Glass has translucent,
  rounded surfaces using the same layout and data.
- Relative and Standings: class-coloured strips, white position blocks, real
  iRating/license badges, actual-player highlight, derived class SoF and session
  summaries. See [relative-standings-design.md](relative-standings-design.md).
- Laptime Log: graph, best band, table, observed completion temperature and
  tri-state incident markers. Head to Head: recent observed-lap comparisons,
  **not sectors**. See [laplog-headtohead-design.md](laplog-headtohead-design.md).
- Radar: crosshair, side warning zones, vertical ahead/rear estimated-distance
  bars. BlindSpot: steady labelled amber/red tiles. See
  [proximity-design.md](proximity-design.md).
- Input Telemetry starts with missing-value dashes instead of fabricated gear
  and speed. Its saved position, DPI and resolution were preserved.
- The lap log's default height is now 620px to fit the graph and table. Saved
  position and DPI fields are preserved.

## Observed checks

| Check | Result |
| --- | --- |
| Full Python suite inside the isolated Windows build environment | 272 passed, exit 0 |
| All frontend `tests/test_*.cjs` | 148 passed, no failures/skips, exit 0 |
| R1 browser: seven harmonized widgets, both skins, four widths, empty/data | 112 states passed |
| R2 browser: Relative/Standings, both skins, native/narrow and lifecycle/security states | 40 states passed |
| R3 browser: lap log/Head to Head, both skins, native/narrow and lifecycle/security states | 40 states passed |
| R4 browser: Radar/BlindSpot, both skins, native/narrow, 12 proximity/lifecycle states | 96 states passed |
| Independent OpenAI source and screenshot reviews for R1–R4 | PASS, no blockers |
| PyInstaller and ZIP packaging | Exit 0 |
| Launched packaged executable | Launcher HTTP 200; 13 overlays discovered |
| Packaged overlay pages | All 26 Original/Glass URLs HTTP 200 with the new stylesheet |
| Packaged new shared CSS/metadata JS | HTTP 200 |
| Packaged Engine.IO polling handshake | HTTP 200, session ID returned |

The four browser probes total **288 checked states** across all 13 overlays.
They use real Flask-rendered pages, real overlay scripts and provider-generated
or explicitly labelled boundary fixtures. Request/socket delivery is controlled
for isolation; this is not live racing validation. The parent also ran each
browser probe and inspected rendered captures. Evidence is local scratch under
`.git/redesign/`, not a runtime dependency or bundled asset.

The existing failure-isolation tests deliberately log `boom`. The NaN lap-counter
regression logs the existing conversion error while verifying incident uncertainty.
Those expected logs are not suite failures. LSP diagnostics could not run because
Biome/TypeScript/basedpyright servers are not installed; no tools were installed
to hide that gap. No Lighthouse score is claimed.

## Build correction

The build initially failed because Spanish `tasklist` output was decoded as
UTF-8 under UTF-8 mode. The process check now compares the ASCII executable name
against raw output bytes. Two regression tests observed RED then GREEN, including
preserving the running-application guard. The subsequent full build succeeded.

## Remaining manual checks and honest limitations

- Test with live iRacing, particularly completed-lap/incident update ordering,
  opponent timing availability, real class/track metadata and camera switches.
- Check the native desktop windows and an OBS Browser Source for readability,
  scaling and transparency over the actual game. Browser and HTTP package checks
  do not prove those scenarios. Glass cannot blur the game behind a transparent
  browser surface.
- Position gains deliberately remain `--`; qualifying rank is not substituted
  for an unconfirmed actual grid position.
- SoF is derived from the known class roster. Partial samples are labelled and
  are not represented as official server SoF.
- Radar distances are lap-progress estimates, not exact lateral positions or
  time-to-collision. Legacy false-on-missing SDK flags cannot be distinguished
  from real false flags by the frontend alone.
- A pre-existing Relative server disconnect callback signature limitation remains
  documented in the R2 design notes. Frontend disconnect/stale clearing is tested.

The source and local executable are ready to try, with the above live-use checks
explicitly outstanding. No release was uploaded and no changes were pushed.
