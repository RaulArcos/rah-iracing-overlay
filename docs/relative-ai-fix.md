# Relative timing and AI-profile accuracy fix

## Sources and math

The [pyirsdk variable reference](https://github.com/kutu/pyirsdk/blob/master/vars.txt)
defines `CarIdxEstTime` as **estimated time to reach current location on track**
(seconds), `CarIdxLapDistPct` as track progress, and `CarIdxF2Time` as race time
behind the leader or fastest lap otherwise. F2 is not physical Relative timing.

`src/relative_timing.py` uses each roster entry's real, finite, positive
`CarClassEstLapTime` as its profile period. Neither personal best nor an invented
90-second fallback supplies that period. Missing or invalid timing produces JSON
`null` / visible `--`, while valid physical progress still selects/orders cars.

For player progress `p`, target progress `q`, player period `T`:

1. Wrap `d = q - p` into `(-0.5, 0.5]` to obtain physical delta `w`.
2. Same class: subtract SDK profile coordinates directly, requiring consistent
   class periods. `gap_source = sdk_class_profile`.
3. Different/unknown classes with both periods available: convert target time
   `t_other` to player-profile seconds with `t_other / T_other * T`.
   `gap_source = sdk_normalized_class_profile`. This normalization does **not**
   establish identical pace-profile shapes across classes.
4. `gap = target_coordinate - player_coordinate + round(w - d) * T`.
   Physical progress selects the start/finish branch; wrapping at half the profile
   time would fail on nonuniform tracks. Inconsistent sign/profile pairs are
   unavailable rather than fabricated.

Example: `T=81.6658`, player `(pct=.99, time=80.9)`, target
`(pct=.005, time=.4)` yields `1.1658 s`, displayed `+1.2s`. Reverse yields
`-1.2s`. A `.1 -> .4` physical interval with profile times `1 -> 70` legitimately
returns `+69.0s`, not the negative half-time branch.

These are SDK **profile estimates**, not measured arrival-time intervals. The
internal `gap_is_estimate` remains true; source is documented in the footer/row
tooltip. The UI shows one decimal, no tilde, seconds in the column heading,
`0.0s` for self, normalized rounded zero, and signed nonzero opponent gaps.
The existing twelve-opponent payload, physical selection, identity, classification,
pit flags and lap deltas remain; six nearby opponents plus player fit the UI.

Track pct must be finite in `[0,1]`; negative/off-track sentinels are excluded.
Index zero is valid; missing, negative or out-of-range player indices yield no
opponents. Short/missing arrays and nonfinite/negative times are unavailable.
Profile coordinates must lie within their own positive period. Zero is accepted
at exact start/finish (`pct=0` or `1`), but treated as unavailable elsewhere.
At the finish endpoint, `(pct=1,time=0)` is normalized to `(1,T)`; at the start,
`(pct=0,time=T)` is normalized to `(0,0)`. Equivalent endpoint encodings must not
add a full lap to an otherwise sub-second gap. Malformed roster sections degrade
to empty metadata rather than discarding other valid telemetry.

## AI and account-profile limits

Shared Relative/Standings metadata uses only explicit roster `CarIsAI`: boolean
or numeric `0/1`; absent, string or other values are unknown. Ratings alone never
identify bots. Explicit bots show `AI`, with no account license/SR/iRating, and
never contribute ratings to SoF. A roster containing a real bot reports **AI
session**, with no numerical SoF. Outside AI contexts the existing exponential
SoF formula, valid human ratings and SDK colors are retained.

Only the observed player's exact placeholder combination is suppressed:
actual bot context, player `CarIsAI=0`, `IRating=1`, `LicString=R0.01` (optional
whitespace), `LicLevel=1`, `LicSubLevel=1`, invalid/missing `LicColor`.
It yields null profile fields and `profile_unavailable_reason=ai_session_placeholder`.
A tooltip explains that the SDK supplies AI-session placeholders, not the online
account profile. Valid human profiles in AI races and genuine Rookie/IR1 profiles
without that context are preserved. **The user's real online profile cannot be
recovered from these fields**; no account API, credentials, caches or guessed
license values are involved.

## Anonymous live evidence and validation

Parent-captured read-only SDK evidence (provided with this task): connected,
player index `0`, best/last lap `-1`, `DriverCarEstLapTime=81.6658`, class IDs `0`,
roster class periods `81.6658`; player `IRating=1`, `LicString=R0.01`, level/sublevel
`1`, `LicColor=0xundefined`, `CarIsAI=0`; bots `CarIsAI=1`, `IRating=0`,
`LicString=R0.00`. One bot had off-track pct `-1`, estimated time `0`.
No names/account IDs were retained. A new explicit read-only probe during this
fix returned `{"startup": false, "connected": false}` and shut down cleanly.
Consequently this fix's browser screenshots are **frozen fixtures, not live proof**.
The fixture reconstructs the reported profile fields in a reduced three-car
roster (player, on-track bot, off-track bot); track-time coordinates are explicit
regression inputs, not a captured live snapshot or a reconstruction of all 25 cars.

RED → GREEN:

- `python -m unittest discover -s tests -p test_relative_ai_accuracy.py`:
  initial six tests produced **13 failures + 1 error**. Examples: cross-class
  old gap `9.0` vs expected `14.49974`; missing timing fabricated `0.9`;
  invalid off-track bot remained in the payload; no `is_ai` field.
  Final expanded focused suite: **8 passing tests**.
- `node --test --test-name-pattern="relative observed AI" tests/test_battle_standings_frontend.cjs`:
  RED actual labels `['+1.17s','0.00s','-0.00s','--']` vs expected physical
  order/one-decimal `['--','+1.2s','0.0s','0.0s']`; then GREEN.
- Existing numeric gap tests now supply explicit SDK periods/coordinates while
  retaining their exact numeric assertions. Missing-profile fallback assertions
  now require null seconds and the precise physical delta. Existing XSS, stale,
  reconnect, pit, theme parity and sign checks remain.
- `python -m unittest discover -s tests`: **288 passed**. Expected injected-error
  logs (including the mocked executable-running build guard) do not represent
  an actual build attempt or test failure.
- `node --test "tests/test_*.cjs"`: **154 passed**, none skipped.
- `python tests/relative_ai_browser.py`: **10 Chromium cases**, zero page errors,
  actual Relative/shared JS via isolated Flask GET routes and stub event transport.
  Original/Glass each cover forward/reverse wrap, nonuniform profile, missing time
  and rounded negative zero; also check literal hostile names, AI/player badges,
  disconnect clearing and three-second staleness. Appearance-settings loading is
  disabled in this harness, so user position/properties endpoints are untouched.
- `git diff --check`: passed (existing Windows LF/CRLF notices only).

Browser artifacts: `.git/relative-ai-debug/browser-evidence.json` plus
`{observed-ai-wrap-ahead,wrap-behind,nonuniform,missing-timing,negative-zero}-{original,glass}.png`.
Every screenshot is explicitly labeled `FROZEN TEST FIXTURE ... NOT LIVE SDK`.
Repeat live probe, if a session is available: `python tests/relative_ai_browser.py --live`.
It performs only startup/freeze/read/shutdown and prints allowlisted anonymous fields.

## Changed files and handoff

- `src/relative_timing.py`: extracted, stateless Relative-only builder (<250 LOC).
- `src/data_provider.py`: import and Relative delegation only in this task.
- `src/race_metadata.py`, `src/common/js/race_metadata.js`: guarded shared metadata
  and bot/profile presentation; no Standings layout changes.
- `src/overlays/relative/relative.html`, `static/relative.js`: units, provenance,
  formatting and physical display order.
- `tests/test_relative_ai_accuracy.py`, `tests/relative_ai_browser.py`: new checks.
- `tests/test_telemetry_accuracy.py`, `tests/test_accuracy_frontend.cjs`,
  `tests/test_battle_standings_frontend.cjs`: affected existing fixtures/assertions.
- `docs/relative-ai-fix.md`: this evidence and accuracy contract.

Parent owns independent review/live verification, ODD tracker updates, final menu
PNG refresh and Windows build. Existing dirty redesign/demo/PNG work is preserved.

### Independent-review correction

Two new regressions reproduced the exact finish-endpoint error and malformed
roster failure: 10 tests initially had 4 failures and 4 errors, then all 10 passed
after the endpoint normalization and roster shape guards. The browser harness now
also exercises zero-at-finish in both directions, for 14 states across both skins.
Live SDK was available for the initial anonymous diagnostic read, but not for the
subsequent validation; no claim of simultaneous matching against live F3 is made.

### Final verification and local build

- Independent OpenAI correction recheck: PASS, 10 focused tests and 22 additional
  public-poll endpoint/nonuniform/mixed-class/malformed-roster probes.
- Parent ran the updated real-script Chromium harness: 14 states across Original
  and Glass, zero page errors. Captures are explicitly frozen fixtures, not live.
- Full Python suite inside the isolated build environment: **290 passed**.
  Full Node suite: **154 passed**, no failures or skipped tests.
- Refreshed all 26 menu PNGs and verified all 26 animated demo/menu selections;
  property hashes stayed unchanged and demos made no live transport/write calls.
- Built `dist/RAH_Telemetry_Overlay/RAH_Telemetry_Overlay.exe` and
  `release/RAH_Telemetry_Overlay-20261107-c13f259.zip`. Parent launched the actual
  executable and passed packaged checks for 26 PNGs, 26 animated demos and 26 menu
  selections, with settings unchanged.
- Packaging initially failed on the independently changed icon's format. Added
  Pillow to **build-only** requirements so PyInstaller can convert the icon in
  its work directory; the user's icon was not edited. The subsequent build passed.

Source remains uncommitted; nothing was pushed. Live validation against iRacing's
F3 after the correction remains outstanding because the SDK disconnected before
validation. The player's real online license/iRating is still unavailable in the
observed AI roster, not recovered or guessed.
