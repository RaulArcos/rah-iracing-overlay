'use strict';

// Theme system tests (T2, S2-S5): resolution precedence, defensive storage,
// shared CSS scoping guarantees, and overlay/launcher includes. Uses only the
// Node built-in test runner; no GUI, server, or real SDK is started.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const repoRoot = path.resolve(__dirname, '..');
const themeJsPath = path.join(repoRoot, 'src', 'common', 'js', 'overlay_theme.js');
const themeCssPath = path.join(repoRoot, 'src', 'common', 'css', 'overlay-theme.css');

test('race skin is opt-in and loads after the existing theme on migrated pages', () => {
    const migrated = ['input_telemetry', 'track_map', 'fuel_finish', 'session_strip',
        'pit_assistant', 'weather', 'broadcast_driver', 'relative', 'standings', 'laptime_graph', 'battle_pace', 'radar', 'blindspot', 'delta'];
    for (const name of migrated) {
        const html = fs.readFileSync(path.join(repoRoot, 'src/overlays', name, `${name}.html`), 'utf8');
        assert.match(html, /class="[^"]*\brah-race\b/);
        assert.ok(html.indexOf('race-system.css') > html.indexOf('overlay-theme.css'));
    }
});

test('input telemetry initial markup never advertises fabricated speed or gear', () => {
    const html = fs.readFileSync(path.join(repoRoot, 'src/overlays/input_telemetry/input_telemetry.html'), 'utf8');
    assert.match(html, /id="gear-display">—</);
    assert.match(html, /id="speed-display">— km\/h</);
});

const OVERLAYS = [
    'input_telemetry',
    'relative',
    'radar',
    'blindspot',
    'track_map',
    'laptime_graph',
];

// Class names that exist in the current overlay base stylesheets. Any shared
// CSS rule that restyles one of them must be scoped to the glass theme, so the
// default (Original) look never overrides per-overlay base CSS.
const EXISTING_OVERLAY_CLASSES = [
    'telemetry-container', 'telemetry-content', 'telemetry-bars', 'telemetry-right',
    'bar', 'bar-fill', 'gear-speed-container',
    'relative-container', 'relative-table',
    'radar-container', 'radar-header', 'nearby-list', 'nearby-item',
    'blindspot-container', 'zone', 'center-zone', 'status-msg',
    'track-map-container', 'laptime-container',
    'header', 'title', 'stats', 'alerts', 'alert',
];

function makeStorage(initial) {
    const store = new Map(Object.entries(initial || {}));
    return {
        getItem(key) { return store.has(key) ? store.get(key) : null; },
        setItem(key, value) { store.set(key, String(value)); },
    };
}

function makeThrowingStorage() {
    return {
        getItem() { throw new DOMException('denied', 'SecurityError'); },
        setItem() { throw new DOMException('denied', 'SecurityError'); },
    };
}

function loadThemeInBrowser({ search = '', storage = null } = {}) {
    const attributes = {};
    const sandbox = {
        console,
        location: { search },
        localStorage: storage,
        document: {
            documentElement: {
                setAttribute(name, value) { attributes[name] = value; },
                getAttribute(name) { return attributes[name] || null; },
            },
        },
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    const code = fs.readFileSync(themeJsPath, 'utf8');
    vm.runInContext(code, sandbox, { filename: themeJsPath });
    return { api: sandbox.RAHOverlayTheme, attributes };
}

test('theme runtime exports the supported theme contract', () => {
    const api = require(themeJsPath);
    assert.deepEqual(api.themes, ['original', 'glass']);
    assert.equal(api.defaultTheme, 'original');
    assert.equal(typeof api.storageKey, 'string');
});

test('resolve(): a valid URL theme takes precedence over the stored one', () => {
    const api = require(themeJsPath);
    assert.equal(api.resolve('glass', null), 'glass');
    assert.equal(api.resolve('glass', 'original'), 'glass');
    assert.equal(api.resolve('original', 'glass'), 'original');
});

test('resolve(): an invalid non-empty URL theme falls back to Original', () => {
    const api = require(themeJsPath);
    assert.equal(api.resolve('neon', 'glass'), 'original');
    assert.equal(api.resolve('Glass', 'glass'), 'original');
    assert.equal(api.resolve('<script>', 'glass'), 'original');
});

test('resolve(): an absent or empty URL theme defers to the stored preference', () => {
    const api = require(themeJsPath);
    assert.equal(api.resolve('', 'glass'), 'glass');
    assert.equal(api.resolve(null, 'glass'), 'glass');
    assert.equal(api.resolve(undefined, 'glass'), 'glass');
});

test('resolve(): empty, invalid, or stale stored values fall back to Original', () => {
    const api = require(themeJsPath);
    assert.equal(api.resolve(null, 'neon'), 'original');
    assert.equal(api.resolve(null, ''), 'original');
    assert.equal(api.resolve(null, null), 'original');
    assert.equal(api.resolve(null, undefined), 'original');
    assert.equal(api.resolve(null, 'original'), 'original');
});

test('apply(): sets the data-rah-theme attribute and rejects invalid values', () => {
    const api = require(themeJsPath);
    const roots = [];
    const root = { setAttribute(name, value) { roots.push([name, value]); } };
    assert.equal(api.apply('glass', root), 'glass');
    assert.equal(api.apply('original', root), 'original');
    assert.equal(api.apply('neon', root), 'original');
    assert.equal(api.apply('', root), 'original');
    assert.equal(api.apply(null, root), 'original');
    assert.equal(api.apply(undefined, root), 'original');
    for (const [name] of roots) assert.equal(name, 'data-rah-theme');
    assert.deepEqual(roots.map(([, value]) => value), [
        'glass', 'original', 'original', 'original', 'original', 'original',
    ]);
});

test('apply(): tolerates a missing root without crashing', () => {
    const api = require(themeJsPath);
    assert.equal(api.apply('glass', null), 'glass');
    assert.equal(api.apply('glass', undefined), 'glass');
});

test('init(): URL theme wins, storage fills in, default otherwise', () => {
    const api = require(themeJsPath);
    const mk = () => ({ setAttribute() {} });
    const cases = [
        [{ location: { search: '?theme=glass' }, storage: makeStorage({ rah_overlay_theme: 'original' }), document: { documentElement: mk() } }, 'glass'],
        [{ location: { search: '' }, storage: makeStorage({ rah_overlay_theme: 'glass' }), document: { documentElement: mk() } }, 'glass'],
        [{ location: { search: '' }, storage: makeStorage({ rah_overlay_theme: 'neon' }), document: { documentElement: mk() } }, 'original'],
        [{ location: { search: '' }, storage: null, document: { documentElement: mk() } }, 'original'],
        [{ location: null, storage: makeStorage({ rah_overlay_theme: 'glass' }), document: { documentElement: mk() } }, 'glass'],
    ];
    for (const [options, expected] of cases) {
        assert.equal(api.init(options), expected, JSON.stringify(options));
    }
});

test('init(): denied localStorage does not crash and falls back', () => {
    const api = require(themeJsPath);
    const attributes = [];
    const resolved = api.init({
        location: { search: '' },
        storage: makeThrowingStorage(),
        document: { documentElement: { setAttribute(n, v) { attributes.push([n, v]); } } },
    });
    assert.equal(resolved, 'original');
    assert.deepEqual(attributes, [['data-rah-theme', 'original']]);
});

test('init(): a missing document does not crash', () => {
    const api = require(themeJsPath);
    assert.equal(api.init({ location: { search: '?theme=glass' }, storage: null, document: null }), 'glass');
});

test('readUrlTheme(): parses, decodes, and survives malformed input', () => {
    const api = require(themeJsPath);
    assert.equal(api.readUrlTheme({ search: '?theme=glass' }), 'glass');
    assert.equal(api.readUrlTheme({ search: '?foo=1&theme=original&bar=2' }), 'original');
    assert.equal(api.readUrlTheme({ search: '?theme=' }), '');
    assert.equal(api.readUrlTheme({ search: '?other=glass' }), null);
    assert.equal(api.readUrlTheme({ search: '' }), null);
    assert.equal(api.readUrlTheme(null), null);
});

test('browser load auto-applies the resolved theme without any page code', () => {
    const urlWins = loadThemeInBrowser({ search: '?theme=glass', storage: makeStorage({ rah_overlay_theme: 'original' }) });
    assert.equal(urlWins.attributes['data-rah-theme'], 'glass');

    const storedWins = loadThemeInBrowser({ search: '', storage: makeStorage({ rah_overlay_theme: 'glass' }) });
    assert.equal(storedWins.attributes['data-rah-theme'], 'glass');

    const denied = loadThemeInBrowser({ search: '', storage: makeThrowingStorage() });
    assert.equal(denied.attributes['data-rah-theme'], 'original');

    const stale = loadThemeInBrowser({ search: '', storage: makeStorage({ rah_overlay_theme: 'neon' }) });
    assert.equal(stale.attributes['data-rah-theme'], 'original');
});

test('browser load with no URL theme and no storage defaults to Original', () => {
    // An overlay opened with no ?theme= and no storage must default to
    // Original, which is the absence of any glass override.
    const run = loadThemeInBrowser({ search: '', storage: null });
    assert.equal(run.attributes['data-rah-theme'], 'original');
});

test('setStored()/getStored(): persist only whitelisted themes, defensively', () => {
    const api = require(themeJsPath);
    const storage = makeStorage();
    assert.equal(api.setStored('glass', storage), true);
    assert.equal(api.getStored(storage), 'glass');
    assert.equal(api.setStored('original', storage), true);
    assert.equal(api.getStored(storage), 'original');

    assert.equal(api.setStored('neon', storage), false);
    assert.equal(api.setStored('', storage), false);
    assert.equal(api.setStored(null, storage), false);
    assert.equal(api.getStored(storage), 'original', 'invalid writes must not change storage');

    const denied = makeThrowingStorage();
    assert.equal(api.setStored('glass', denied), false);
    assert.equal(api.getStored(denied), null);
    assert.equal(api.getStored(null), null);
});

test('current(): reports the applied theme with a safe default', () => {
    const api = require(themeJsPath);
    const attributes = { 'data-rah-theme': 'glass' };
    const doc = { documentElement: { getAttribute: (n) => attributes[n] || null } };
    assert.equal(api.current(doc), 'glass');
    attributes['data-rah-theme'] = 'neon';
    assert.equal(api.current(doc), 'original');
    assert.equal(api.current({ documentElement: null }), 'original');
    assert.equal(api.current(null), 'original');
});

function readCss() {
    return fs.readFileSync(themeCssPath, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
}

function selectorParts(css) {
    // Split into declaration blocks and return each block's selector text.
    return css.split('}')
        .map((block) => {
            const brace = block.indexOf('{');
            return brace === -1 ? '' : block.slice(0, brace);
        })
        .filter((selector) => selector.trim().length > 0);
}

test('shared CSS never restyles existing overlay classes outside the glass scope', () => {
    const css = readCss();
    const violations = [];
    for (const rule of selectorParts(css)) {
        for (const part of rule.split(',')) {
            const tokens = (part.match(/\.[\w-]+/g) || []).map((t) => t.slice(1));
            const touchesExisting = tokens.some((t) => EXISTING_OVERLAY_CLASSES.includes(t));
            const bareRoot = /\b(body|html)\b/.test(part) && !part.includes(':root');
            if ((touchesExisting || bareRoot) && !part.includes('[data-rah-theme')) {
                violations.push(part.trim());
            }
        }
    }
    assert.deepEqual(violations, [], 'every override of existing classes must be glass-scoped');
});

test('shared CSS provides glass surfaces for all six current overlays', () => {
    const css = readCss();
    for (const name of OVERLAYS) {
        const containers = {
            input_telemetry: '.telemetry-container',
            relative: '.relative-container',
            radar: '.radar-container',
            blindspot: '.blindspot-container',
            track_map: '.track-map-container',
            laptime_graph: '.laptime-container',
        };
        const scoped = selectorParts(css).some((rule) =>
            rule.includes('[data-rah-theme="glass"]') && rule.includes(containers[name]));
        assert.ok(scoped, `${containers[name]} must have a glass-scoped rule`);
    }
});

test('shared CSS defines the reusable widget utility classes', () => {
    const css = readCss();
    for (const utility of [
        '.rah-card', '.rah-card__header', '.rah-list', '.rah-row', '.rah-grid',
        '.rah-metric', '.rah-metric__label', '.rah-metric__value',
        '.rah-status', '.rah-num',
    ]) {
        assert.match(css, new RegExp(utility.replace(/[.]/g, '\\.')));
    }
    assert.match(css, /tabular-nums/);
});

test('every overlay page includes the theme assets after its base stylesheet', () => {
    for (const name of OVERLAYS) {
        const html = fs.readFileSync(path.join(repoRoot, `src/overlays/${name}/${name}.html`), 'utf8');
        assert.match(html, /overlay-theme\.css/, `${name} must link the shared theme stylesheet`);
        assert.match(html, /overlay_theme\.js/, `${name} must include the theme runtime`);
        assert.match(html, new RegExp(`${name}\\.css`), `${name} must keep its base stylesheet`);
        assert.match(html, /socket\.io\.min\.js/, `${name} must keep the socket runtime`);
        assert.ok(
            html.indexOf(`${name}.css`) < html.indexOf('overlay-theme.css'),
            `${name}: theme stylesheet must load after the base stylesheet`,
        );
    }
});

test('launcher exposes an accessible selector wired to the theme runtime', () => {
    const html = fs.readFileSync(path.join(repoRoot, 'src/interface/index.html'), 'utf8');
    assert.match(html, /<label[^>]*for="themeSelect"/);
    assert.match(html, /<select[^>]*id="themeSelect"/);
    assert.match(html, /<option value="original"[^>]*selected/);
    assert.match(html, /<option value="glass"/);
    assert.match(html, /overlay_theme\.js/);

    const mainJs = fs.readFileSync(path.join(repoRoot, 'src/interface/static/main.js'), 'utf8');
    assert.match(mainJs, /themeSelect/);
    assert.match(mainJs, /RAHOverlayTheme/);
    assert.match(mainJs, /RAHOverlayTheme\.setStored/);

    const launchFn = /function launchOverlay[\s\S]*?\n}/.exec(mainJs);
    assert.ok(launchFn, 'launchOverlay must still exist');
    assert.match(launchFn[0], /theme/, 'launch request must carry the selected theme');

    const openFn = /function openOverlayUrl[\s\S]*?\n}/.exec(mainJs);
    assert.ok(openFn, 'openOverlayUrl must exist');
    assert.match(openFn[0], /theme/, 'opened URL must pin the selected theme');
});

test('docs describe the URL contract and precedence', () => {
    const docs = fs.readFileSync(path.join(repoRoot, 'docs/overlay-themes.md'), 'utf8');
    assert.match(docs, /theme=original\|glass/);
    assert.match(docs, /precedence/i);
    assert.match(docs, /glass/i);
    assert.match(docs, /rah-card/);
});
