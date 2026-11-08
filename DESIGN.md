# RAH race overlay design system

## 1. Direction and references
The user's eight RaceLab screenshots are the visual reference, not assets to
copy. Keep their dense broadcast hierarchy: title strip, high-contrast numbers,
aligned rows, gold column labels, white position blocks and semantic lap colours.
Original retains RAH's red identity; Glass uses the same anatomy and typography.
The dotted blue marketing backdrop in the references is NOT an overlay background.

## 2. Audience and constraints
Drivers need information at a glance without losing sight of the track.
Streamers need legible lower thirds at scaled output sizes. No page-level
background, network fonts, new framework, or fake telemetry. Preserve positioning
hooks, element IDs, event schemas and the user's saved window settings.

## 3. Tokens
- Surface: Original #141414, raised #232323, inset #0d0d0d.
- Ink: #f5f5f5; secondary #b7bac2. Rule: rgba(255,255,255,.12).
- Brand: #ed2727. Labels/highlight: #f2ca52. Improved: #55dd8d;
  slower: #ff6868; session best: #e46cf0. Colour never replaces a label or sign.
- Glass: neutral charcoal rgba(22,25,32,.72), raised rgba(255,255,255,.055),
  bright top rim, subtle diagonal highlight, 14px blur as enhancement only.
  A transparent OBS/desktop window cannot blur the game behind it.
- Type: Segoe UI/Arial for body and headers, Consolas/Cascadia Mono for numbers.
  Labels 10px, status/footer 11px, headers 12px, metadata 14px,
  metrics 20px, primary metrics 26px, driver name 24px, gear 42px.
- Spacing: 4px base; 8px compact gap; 12px panel inset and cell gap.
  Divider 1px; brand strip 3px; header height at least 28px.
- Radii: Original 2px, small components 2px; Glass panel 12px, inset 6px.

## 4. Geometry
Panels are native-size transparent widgets, not responsive landing pages.
Existing desktop dimensions are the upper bounds. Input Telemetry stays inside
640x160. Metric grids use minmax(0,1fr), labels remain readable, and values align
with tabular numerals. At narrower browser widths a widget may scale to its
container, never silently crop important data. No forced extra viewport height.

## 5. Reusable primitives
- `.rah-race`: opt-in panel skin. Existing not-yet-migrated overlays retain their
  prior appearance until their own slice, avoiding an accidental global restyle.
- `.rah-card__header`: full-width title band with a red top strip and right status.
- `.rah-metric`: label/value cell with subtle column rules, not nested cards.
- `.rah-position`: white square, dark number; `.rah-class-mark`: narrow class stripe.
- `.rah-badge`: compact metadata marker, never invented identity/rating.
- `.rah-table-row`: striped row; `.rah-player`: amber emphasis for actual player.
- `.rah-best`, `.rah-improved`, `.rah-slower`, `.rah-muted`: semantic text colours.
- `.rah-footer`: subdued explanatory line with a separator; stay legible.
States: live, missing, stale, warning and error retain existing text and values.
Missing values stay dashes; no decorative random numbers. Headers and fields do
not animate. Reduced-motion preference disables legacy decorative transitions.

## 6. Accessibility and motion
Status includes text; timing includes signs. Preserve readable white/gold text
and use medium weight labels. No blinking, pulsing or gratuitous hover effects
on read-only widgets. Changes should not move columns as values update.

## 7. Validation
Use real Chromium with isolated fixture telemetry, at native window sizes and
375/768/1280px browser widths. Check Original and Glass, empty/data/stale states,
JS errors, clipped text and panel bounds. Fixture screenshots are simulated,
not proof of live iRacing accuracy. Keep functional Python and Node suites green.

## 8. Accepted debt and handoff
The launcher follows the portfolio's quieter presentation: readable warm-gray
secondary text, solid tool panels, no scanning beams, background drift, blinking
status or repeated entrance animations. Real running state and saving feedback
remain visible. Original/Glass race widgets and their telemetry contracts are
unchanged. Source changes require a separate build to reach the downloadable app.
Live iRacing, OBS and desktop transparency still require manual checks.
R2 implements real roster ratings and class metadata; R3 implements lap observations
and recent-lap comparison; R4 implements proximity visuals. Their dedicated JS
and provider modules, not shared CSS alone, supply those behaviors. Position gains
remain unavailable without a confirmed actual race-start source. No React tooling
is needed (vanilla JS).
