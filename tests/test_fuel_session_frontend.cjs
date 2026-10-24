'use strict';

// Fuel & Finish and Session Strip front-end tests (T3, S2-S5).
// Runs the real overlay scripts against a stub DOM via node:vm and asserts
// the rendered text/classes. Uses only the Node built-in test runner.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const repoRoot = path.resolve(__dirname, '..');

function makeElement(id) {
    const classes = new Set();
    return {
        id,
        textContent: '',
        innerHTML: '',
        classes,
        classList: {
            add(name) { classes.add(name); },
            remove(name) { classes.delete(name); },
            toggle(name, force) {
                const on = force === undefined ? !classes.has(name) : Boolean(force);
                if (on) classes.add(name); else classes.delete(name);
            },
        },
    };
}

function loadOverlay(name, options = {}) {
    const elements = {};
    const handlers = {};
    const intervals = [];
    const clock = { now: 1000000 };
    const attributes = { 'data-rah-theme': options.theme || 'original' };
    let readyHandler = null;
    let ioCall = null;
    const document = {
        documentElement: {
            getAttribute: (key) => attributes[key] || null,
            setAttribute: (key, value) => { attributes[key] = value; },
        },
        addEventListener(event, handler) {
            if (event === 'DOMContentLoaded') readyHandler = handler;
        },
        getElementById(id) {
            if (!elements[id]) elements[id] = makeElement(id);
            return elements[id];
        },
    };
    const io = (namespace, ioOptions) => {
        ioCall = { namespace, options: ioOptions };
        return {
            on(event, handler) { handlers[event] = handler; },
        };
    };
    const sandbox = {
        document,
        io,
        console,
        Date: { now: () => clock.now },
        setInterval: (fn, ms) => { intervals.push({ fn, ms }); return intervals.length; },
        clearInterval: () => {},
    };
    vm.createContext(sandbox);
    const relativePath = `src/overlays/${name}/static/${name}.js`;
    vm.runInContext(fs.readFileSync(path.join(repoRoot, relativePath), 'utf8'), sandbox, { filename: relativePath });
    assert.ok(readyHandler, 'script must register a DOMContentLoaded handler');
    readyHandler();
    const text = (id) => elements[id].textContent;
    const snapshot = () => Object.fromEntries(
        Object.entries(elements).map(([id, el]) => [id, [el.textContent, [...el.classes].sort()]]));
    return { elements, handlers, intervals, clock, ioCall, text, snapshot };
}

function fuelPayload(overrides = {}) {
    return {
        fuel_level_l: 42.5, fuel_level_pct: 42.5,
        avg_burn_l_per_lap: 1.55, burn_sample_count: 4, burn_source: 'observed_clean_laps',
        laps_of_fuel: 27.42,
        finish_laps_remaining: 5, finish_basis: 'laps_remaining',
        finish_fuel_needed_l: 7.75, finish_fuel_to_add_l: 0,
        is_estimate: true, advisory: true,
        ...overrides,
    };
}

function stripPayload(overrides = {}) {
    return {
        session_type: 'Race', limit: 'laps', session_laps_total: 20, session_time_total_s: null,
        laps_remaining: 12, laps_remaining_source: 'SessionLapsRemainEx', time_remaining_s: null,
        state: 'racing', state_code: 4, flags: ['green'],
        position: 3, class_position: 2, lap: 9,
        ...overrides,
    };
}

const UNAVAILABLE = '--';

test('fuel overlay joins the dedicated namespace with unbounded reconnection', () => {
    const { ioCall } = loadOverlay('fuel_finish');
    assert.equal(ioCall.namespace, '/fuel_finish');
    assert.equal(ioCall.options.reconnection, true);
    assert.equal(ioCall.options.reconnectionAttempts, Infinity);
});

test('fuel overlay renders measured fuel, burn and finish values', () => {
    const o = loadOverlay('fuel_finish');
    o.handlers.fuel_finish_update(fuelPayload());
    assert.equal(o.text('fuel-level'), '42.5');
    assert.equal(o.text('fuel-pct'), '43%');
    assert.equal(o.text('fuel-burn'), '1.55');
    assert.equal(o.text('fuel-laps'), '27.4');
    assert.equal(o.text('fuel-finish-laps'), '5');
    assert.equal(o.text('fuel-needed'), '7.8');
    assert.equal(o.text('fuel-add'), '0.0');
    assert.equal(o.text('fuel-samples'), '4 laps');
    assert.match(o.text('fuel-basis'), /laps remaining/i);
});

test('fuel overlay shows zero fuel as a real zero and null as unavailable', () => {
    const o = loadOverlay('fuel_finish');
    o.handlers.fuel_finish_update(fuelPayload({ fuel_level_l: 0, fuel_level_pct: 0, laps_of_fuel: 0 }));
    assert.equal(o.text('fuel-level'), '0.0');
    assert.equal(o.text('fuel-pct'), '0%');
    assert.equal(o.text('fuel-laps'), '0.0');

    o.handlers.fuel_finish_update(fuelPayload({
        fuel_level_l: null, fuel_level_pct: null, avg_burn_l_per_lap: null, burn_sample_count: 0,
        laps_of_fuel: null, finish_laps_remaining: null, finish_basis: null,
        finish_fuel_needed_l: null, finish_fuel_to_add_l: null,
    }));
    for (const id of ['fuel-level', 'fuel-pct', 'fuel-burn', 'fuel-laps', 'fuel-finish-laps',
        'fuel-needed', 'fuel-add', 'fuel-basis']) {
        assert.equal(o.text(id), UNAVAILABLE, id);
    }
    assert.equal(o.text('fuel-samples'), '0 laps');
});

test('fuel overlay labels timed finish values as conservative estimates', () => {
    const o = loadOverlay('fuel_finish');
    o.handlers.fuel_finish_update(fuelPayload({
        finish_basis: 'timed_conservative_estimate', finish_laps_remaining: 7.63,
    }));
    assert.match(o.text('fuel-basis'), /timed/i);
    assert.match(o.text('fuel-basis'), /conservative/i);
    assert.equal(o.text('fuel-finish-laps'), '7.6');
});

test('fuel overlay treats null and malformed payloads as unavailable', () => {
    const o = loadOverlay('fuel_finish');
    o.handlers.fuel_finish_update(fuelPayload());
    for (const bad of [null, undefined, 'x', 7, []]) {
        o.handlers.fuel_finish_update(bad);
        assert.equal(o.text('fuel-level'), UNAVAILABLE);
        assert.equal(o.text('fuel-add'), UNAVAILABLE);
        assert.match(o.text('fuel-status'), /no data/i);
    }
    o.handlers.fuel_finish_update(fuelPayload({ fuel_level_l: 'x', avg_burn_l_per_lap: NaN, laps_of_fuel: Infinity }));
    assert.equal(o.text('fuel-level'), UNAVAILABLE);
    assert.equal(o.text('fuel-burn'), UNAVAILABLE);
    assert.equal(o.text('fuel-laps'), UNAVAILABLE);
});

test('fuel overlay clears stale data on disconnect, connect_error and silence', () => {
    for (const event of ['disconnect', 'connect_error']) {
        const o = loadOverlay('fuel_finish');
        o.handlers.fuel_finish_update(fuelPayload());
        assert.equal(o.text('fuel-level'), '42.5');
        o.handlers[event]();
        assert.equal(o.text('fuel-level'), UNAVAILABLE, event);
        assert.match(o.text('fuel-status'), /disconnected/i);
    }

    const o = loadOverlay('fuel_finish');
    o.handlers.fuel_finish_update(fuelPayload());
    assert.equal(o.intervals.length, 1, 'one local stale timer');
    o.clock.now += 1000;
    o.intervals[0].fn();
    assert.equal(o.text('fuel-level'), '42.5', 'fresh data survives the timer');
    o.clock.now += 10000;
    o.intervals[0].fn();
    assert.equal(o.text('fuel-level'), UNAVAILABLE);
    assert.match(o.text('fuel-status'), /stale|no data/i);

    o.handlers.connect();
    assert.match(o.text('fuel-status'), /waiting/i);
});

test('fuel overlay sets metadata via textContent only', () => {
    const o = loadOverlay('fuel_finish');
    o.handlers.fuel_finish_update(fuelPayload({ finish_basis: '<img src=x onerror=alert(1)>', burn_source: '<b>x</b>' }));
    for (const el of Object.values(o.elements)) {
        assert.equal(el.innerHTML, '');
    }
    const source = fs.readFileSync(path.join(repoRoot, 'src/overlays/fuel_finish/static/fuel_finish.js'), 'utf8');
    assert.doesNotMatch(source, /innerHTML|insertAdjacentHTML|document\.write/);
});

test('session strip joins its namespace and renders a lap-limited race', () => {
    const o = loadOverlay('session_strip');
    assert.equal(o.ioCall.namespace, '/session_strip');
    assert.equal(o.ioCall.options.reconnectionAttempts, Infinity);
    o.handlers.session_strip_update(stripPayload());
    assert.equal(o.text('strip-type'), 'Race');
    assert.equal(o.text('strip-limit'), 'LAPS');
    assert.equal(o.text('strip-state'), 'RACING');
    assert.equal(o.text('strip-flag'), 'GREEN');
    assert.equal(o.text('strip-laps'), '12');
    assert.equal(o.text('strip-time'), UNAVAILABLE);
    assert.equal(o.text('strip-pos'), 'P3');
    assert.equal(o.text('strip-class-pos'), 'C2');
    assert.equal(o.text('strip-lap'), '9');
});

test('session strip formats time remaining and keeps a real zero', () => {
    const o = loadOverlay('session_strip');
    o.handlers.session_strip_update(stripPayload({
        limit: 'time', laps_remaining: null, time_remaining_s: 754.5,
    }));
    assert.equal(o.text('strip-time'), '12:34');
    assert.equal(o.text('strip-limit'), 'TIME');
    assert.equal(o.text('strip-laps'), UNAVAILABLE);
    o.handlers.session_strip_update(stripPayload({ time_remaining_s: 3725 }));
    assert.equal(o.text('strip-time'), '1:02:05');
    o.handlers.session_strip_update(stripPayload({ time_remaining_s: 0, laps_remaining: 0 }));
    assert.equal(o.text('strip-time'), '0:00');
    assert.equal(o.text('strip-laps'), '0');
});

test('session strip never fabricates values for nulls and unlimited sessions', () => {
    const o = loadOverlay('session_strip');
    o.handlers.session_strip_update(stripPayload({
        session_type: null, limit: null, session_laps_total: null, laps_remaining: null,
        time_remaining_s: null, state: null, state_code: null, flags: null,
        position: null, class_position: null, lap: null,
    }));
    for (const id of ['strip-type', 'strip-limit', 'strip-state', 'strip-flag', 'strip-laps',
        'strip-time', 'strip-pos', 'strip-class-pos', 'strip-lap']) {
        assert.equal(o.text(id), UNAVAILABLE, id);
    }
    o.handlers.session_strip_update(stripPayload({ limit: 'unlimited', laps_remaining: null }));
    assert.equal(o.text('strip-limit'), 'UNLIMITED');
    assert.equal(o.text('strip-laps'), UNAVAILABLE);
});

test('session strip distinguishes no flags from unavailable flags and ranks them', () => {
    const o = loadOverlay('session_strip');
    o.handlers.session_strip_update(stripPayload({ flags: [] }));
    assert.equal(o.text('strip-flag'), 'NONE');
    o.handlers.session_strip_update(stripPayload({ flags: ['green', 'yellow', 'blue'] }));
    assert.equal(o.text('strip-flag'), 'YELLOW');
    assert.ok(o.elements['strip-flag'].classes.has('rah-status--warn'));
    o.handlers.session_strip_update(stripPayload({ flags: ['green', 'red'] }));
    assert.equal(o.text('strip-flag'), 'RED');
    assert.ok(o.elements['strip-flag'].classes.has('rah-status--bad'));
    assert.ok(!o.elements['strip-flag'].classes.has('rah-status--warn'));
    o.handlers.session_strip_update(stripPayload({ flags: ['green'] }));
    assert.ok(o.elements['strip-flag'].classes.has('rah-status--ok'));
    o.handlers.session_strip_update(stripPayload({ flags: ['start_hidden'] }));
    assert.equal(o.text('strip-flag'), 'START HIDDEN');
});

test('session strip clears on null payloads, disconnect, connect_error and silence', () => {
    for (const event of ['disconnect', 'connect_error']) {
        const o = loadOverlay('session_strip');
        o.handlers.session_strip_update(stripPayload());
        o.handlers[event]();
        assert.equal(o.text('strip-pos'), UNAVAILABLE, event);
        assert.match(o.text('strip-status'), /disconnected/i);
    }
    const o = loadOverlay('session_strip');
    o.handlers.session_strip_update(stripPayload());
    o.handlers.session_strip_update(null);
    assert.equal(o.text('strip-laps'), UNAVAILABLE);
    assert.match(o.text('strip-status'), /no data/i);

    o.handlers.session_strip_update(stripPayload());
    o.clock.now += 10000;
    o.intervals[0].fn();
    assert.equal(o.text('strip-laps'), UNAVAILABLE);
    o.handlers.connect();
    assert.match(o.text('strip-status'), /waiting/i);
});

test('session strip sets hostile metadata via textContent only', () => {
    const o = loadOverlay('session_strip');
    o.handlers.session_strip_update(stripPayload({ session_type: '<img src=x onerror=alert(1)>' }));
    assert.equal(o.text('strip-type'), '<img src=x onerror=alert(1)>');
    for (const el of Object.values(o.elements)) {
        assert.equal(el.innerHTML, '');
    }
    const source = fs.readFileSync(path.join(repoRoot, 'src/overlays/session_strip/static/session_strip.js'), 'utf8');
    assert.doesNotMatch(source, /innerHTML|insertAdjacentHTML|document\.write/);
});

test('both themes render exactly the same data', () => {
    for (const [name, event, payload] of [
        ['fuel_finish', 'fuel_finish_update', fuelPayload()],
        ['session_strip', 'session_strip_update', stripPayload()],
    ]) {
        const original = loadOverlay(name, { theme: 'original' });
        const glass = loadOverlay(name, { theme: 'glass' });
        original.handlers[event](payload);
        glass.handlers[event](payload);
        assert.deepEqual(glass.snapshot(), original.snapshot(), name);
        assert.ok(Object.keys(glass.snapshot()).length > 5, `${name} must render several elements`);
    }
});

for (const name of ['fuel_finish', 'session_strip']) {
    test(`${name} page follows the overlay conventions and defines every id it uses`, () => {
        const dir = `src/overlays/${name}`;
        const html = fs.readFileSync(path.join(repoRoot, dir, `${name}.html`), 'utf8');
        assert.match(html, /overlay-theme\.css/);
        assert.match(html, /overlay_theme\.js/);
        assert.match(html, /socket\.io\.min\.js/);
        assert.ok(html.indexOf(`${name}.css`) < html.indexOf('overlay-theme.css'),
            'theme stylesheet must load after the base stylesheet');
        assert.match(html, /rah-card/);
        assert.match(html, /pywebview-drag-region/);

        const js = fs.readFileSync(path.join(repoRoot, dir, 'static', `${name}.js`), 'utf8');
        const ids = [...js.matchAll(/getElementById\('([\w-]+)'\)/g)].map((m) => m[1]);
        assert.ok(ids.length >= 8, 'script must look up its elements by id');
        for (const id of ids) {
            assert.match(html, new RegExp(`id="${id}"`), `${name}.html must define #${id}`);
        }

        const properties = JSON.parse(fs.readFileSync(path.join(repoRoot, dir, 'properties.json'), 'utf8'));
        assert.equal(properties.name, name);
        assert.ok(properties.display_name && properties.description);
        assert.ok(properties.resolution.width > 0 && properties.resolution.height > 0);
        assert.ok(fs.existsSync(path.join(repoRoot, dir, 'static', `${name}.css`)));
    });
}

test('new overlay stylesheets keep the original look as the default', () => {
    for (const name of ['fuel_finish', 'session_strip']) {
        const css = fs.readFileSync(path.join(repoRoot, `src/overlays/${name}/static/${name}.css`), 'utf8');
        assert.doesNotMatch(css, /data-rah-theme/, 'theme overrides live in the shared stylesheet only');
        assert.match(css, /background:\s*rgba\(0,\s*0,\s*0,\s*0\)/);
    }
});

test('fuel grid layout beats the later-loaded shared .rah-grid rule (T7 computed-layout finding)', () => {
    // Browser probe: with a plain `.fuel-grid` rule the shared `.rah-grid`
    // (same specificity, loaded afterwards) won and rendered 3 columns
    // instead of the designed 4. A compound selector wins on specificity.
    const css = fs.readFileSync(path.join(repoRoot, 'src/overlays/fuel_finish/static/fuel_finish.css'), 'utf8');
    assert.match(css, /\.rah-grid\.fuel-grid\s*\{[^}]*grid-template-columns:\s*repeat\(4,\s*minmax\(0,\s*1fr\)\)/);
    assert.doesNotMatch(css, /^\.fuel-grid\s*\{/m);
    const html = fs.readFileSync(path.join(repoRoot, 'src/overlays/fuel_finish/fuel_finish.html'), 'utf8');
    assert.match(html, /class="rah-grid fuel-grid"/);
});

test('fuel & session docs describe routes, units, sampling and live validation', () => {
    const docs = fs.readFileSync(path.join(repoRoot, 'docs/fuel-session.md'), 'utf8');
    for (const pattern of [
        /\/overlay\/fuel_finish/, /\/overlay\/session_strip/,
        /fuel_finish_update/, /session_strip_update/,
        /liters/i, /FuelLevelPct/, /SessionLapsRemainEx/, /advisory/i,
        /refuel/i, /conservative/i, /live validation/i,
    ]) {
        assert.match(docs, pattern);
    }
});
