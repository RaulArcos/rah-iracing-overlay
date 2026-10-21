# Overlay themes: Original RAH and Glass

This document describes the dual-theme system shared by every overlay
(ODD task T2, specs S2–S5): how a theme is selected, how the launcher
persists the choice, how browser/OBS URLs override it, and the exact
interface new overlays must use.

Run the theme regression suites with the standard runners only:

```bash
python -B -m unittest discover -s tests -p "test_*.py"
node --test tests/test_themes.cjs
```

## Themes

| Theme       | Look                                                                 |
|-------------|----------------------------------------------------------------------|
| `original`  | The existing RAH look. Default everywhere; no CSS of any overlay is overridden. |
| `glass`     | iOS-inspired translucent fill, soft border, subtle gradient.          |

Honest limitation: `backdrop-filter` can only blur page content behind the
element. It cannot sample the game behind a transparent OBS browser source or
a transparent pywebview window. Glass therefore relies on the translucent
surface; the blur is a progressive enhancement only.

## How a theme is selected (precedence)

The shared runtime `/common/js/overlay_theme.js` resolves the theme on every
overlay page, in this order:

1. `?theme=original|glass` on the page URL — highest precedence. An explicit
   but invalid value (for example `?theme=neon`) is rejected and resolves to
   `original`. An empty value (`?theme=`) counts as absent.
2. The stored preference (`localStorage` key `rah_overlay_theme`). Invalid,
   empty, or stale stored values resolve to `original`. If storage is denied
   or missing (some embedded web views, OBS sources), the read fails closed
   to `original` without crashing.
3. `original`.

The resolved theme is written to the root element:
`<html data-rah-theme="original|glass">`. Selection is entirely client-side;
the `/overlay/<name>` route serves identical HTML regardless of `?theme=`.

## Using themes

### Browser / OBS

Append the query parameter to any overlay URL:

```
http://127.0.0.1:8085/overlay/input_telemetry?theme=glass
http://127.0.0.1:8085/overlay/relative?theme=original
```

### Desktop launcher

The launcher header has a visible, keyboard-accessible `<select>`
(`Original RAH` / `Glass`, default `Original RAH`). The choice is persisted in
the launcher's `localStorage` and sent with every `/launch` request. The
backend keeps a small explicit whitelist `('original', 'glass')` and only ever
appends a whitelisted `?theme=` to the pywebview window URL; a missing or
non-whitelisted value keeps the plain URL, so older clients behave exactly as
before. Re-launches (positioning toggles) reuse the theme pinned for that
overlay in memory; no settings file or `properties.json` is touched.

## Exact interface for new overlays (T3+)

Every overlay page includes the two shared assets in `<head>`, after its own
base stylesheet:

```html
<link rel="stylesheet" href="{{ url_for('interface.serve_common_css', filename='overlay-theme.css') }}">
<script src="{{ url_for('serve_common_js', filename='overlay_theme.js') }}"></script>
```

The script auto-applies the resolved theme while still in `<head>` (it only
touches `document.documentElement`), so no page code is required. Pages that
need to know the theme can call:

```js
RAHOverlayTheme.current();                  // 'original' | 'glass'
RAHOverlayTheme.resolve(urlValue, stored);  // pure precedence function
RAHOverlayTheme.apply(theme, rootElement);  // validate + set attribute
RAHOverlayTheme.getStored(storage);         // validated value or null
RAHOverlayTheme.setStored(theme, storage);  // persist; false when denied/invalid
```

All storage helpers catch denied/throwing storage and never crash.

### Shared stylesheet rules

`/common/css/overlay-theme.css` defines:

- Design tokens on `:root` (`--rah-glass-*`, `--rah-original-*`).
- Glass overrides for the six current overlay containers and their inner
  elements (`.telemetry-container`, `.relative-container`, `.radar-container`,
  `.blindspot-container`, `.track-map-container`, `.laptime-container`,
  tables, zones, alerts, chips, canvases). **Every rule that restyles an
  existing overlay class is scoped under `html[data-rah-theme="glass"]`**, so
  the default (Original) rendering never overrides per-overlay base CSS such
  as `input_telemetry.css`.
- Reusable widget utilities, already themed for both looks:

```html
<div class="rah-card">
  <div class="rah-card__header">Fuel &amp; Finish <span class="rah-status rah-status--warn">1.9 laps left</span></div>
  <div class="rah-grid">
    <div class="rah-metric">
      <span class="rah-metric__label">Fuel</span>
      <span class="rah-metric__value rah-num">1.94<span class="rah-metric__unit">L</span></span>
    </div>
  </div>
  <ul class="rah-list">
    <li class="rah-row"><span>Bob</span><span class="rah-num">+0.42s</span></li>
  </ul>
</div>
```

Available utilities: `.rah-card`, `.rah-card__header`, `.rah-list`,
`.rah-row`, `.rah-grid`, `.rah-metric`, `.rah-metric__label`,
`.rah-metric__value`, `.rah-metric__unit`, `.rah-status` (with
`--ok` / `--warn` / `--bad` modifiers), and `.rah-num` (tabular numerals for
stable columns while telemetry updates).

New widgets gain the Glass look automatically by using these classes; do not
add unscoped rules that restyle existing overlay classes.
