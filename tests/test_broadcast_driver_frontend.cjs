'use strict';

// Broadcast Driver Card front-end tests (T6, S2-S5).
// Runs the real overlay script against a stub DOM via node:vm and asserts the
// rendered text/classes. Uses only the Node built-in test runner.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const repoRoot = path.resolve(__dirname, '..');
const UNAVAILABLE = '\u2014';
const EVENT = 'broadcast_driver_update';
const IDS = ['bd-number', 'bd-name', 'bd-class', 'bd-position', 'bd-class-position', 'bd-laps',
    'bd-last', 'bd-best', 'bd-pit', 'bd-session', 'bd-camera'];

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

function loadOverlay(options = {}) {
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
        return { on(event, handler) { handlers[event] = handler; } };
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
    const relativePath = 'src/overlays/broadcast_driver/static/broadcast_driver.js';
    vm.runInContext(fs.readFileSync(path.join(repoRoot, relativePath), 'utf8'), sandbox, { filename: relativePath });
    assert.ok(readyHandler, 'script must register a DOMContentLoaded handler');
    readyHandler();
    const text = (id) => elements[id].textContent;
    const has = (id, cls) => elements[id].classes.has(cls);
    const snapshot = () => Object.fromEntries(
        Object.entries(elements).map(([id, el]) => [id, [el.textContent, [...el.classes].sort()]]));
    return { elements, handlers, intervals, clock, ioCall, text, has, snapshot, update: handlers[EVENT] };
}

function payload(overrides = {}) {
    return {
        available: true, reason: null, camera_car_idx: 2, identity_available: true,
        name: 'Bob', car_number: '7', class_id: 12, class_name: 'LMP2',
        position: 1, class_position: 1, laps_completed: 7, last_lap_s: 88.25, best_lap_s: 87.5,
        on_pit_road: false, session_type: 'Race', source: 'CamCarIdx',
        ...overrides,
    };
}

const UNKNOWN_FIELDS = {
    name: null, car_number: null, class_id: null, class_name: null, position: null,
    class_position: null, laps_completed: null, last_lap_s: null, best_lap_s: null,
    on_pit_road: null, session_type: null,
};

test('overlay joins its dedicated namespace with unbounded reconnection', () => {
    const { ioCall } = loadOverlay();
    assert.equal(ioCall.namespace, '/broadcast_driver');
    assert.equal(ioCall.options.reconnection, true);
    assert.equal(ioCall.options.reconnectionAttempts, Infinity);
});

test('renders the camera-followed driver with formatted ranks and lap times', () => {
    const o = loadOverlay();
    o.update(payload());
    assert.equal(o.text('bd-number'), '#7');
    assert.equal(o.text('bd-name'), 'Bob');
    assert.equal(o.text('bd-class'), 'LMP2');
    assert.equal(o.text('bd-position'), 'P1');
    assert.equal(o.text('bd-class-position'), 'C1');
    assert.equal(o.text('bd-laps'), '7');
    assert.equal(o.text('bd-last'), '1:28.250');
    assert.equal(o.text('bd-best'), '1:27.500');
    assert.equal(o.text('bd-pit'), 'ON TRACK');
    assert.equal(o.text('bd-session'), 'Race');
    assert.equal(o.text('bd-camera'), '2');
    assert.equal(o.text('bd-status'), 'Live');
    assert.ok(o.has('bd-status', 'rah-status--ok'));
});

test('lap times keep minutes, padding and rounding correct', () => {
    const o = loadOverlay();
    o.update(payload({ last_lap_s: 5.5, best_lap_s: 59.9996 }));
    assert.equal(o.text('bd-last'), '0:05.500');
    assert.equal(o.text('bd-best'), '1:00.000');
    o.update(payload({ last_lap_s: 125.0 }));
    assert.equal(o.text('bd-last'), '2:05.000');
});

test('pit road is stated in text and zero laps and camera index 0 are real values', () => {
    const o = loadOverlay();
    o.update(payload({ on_pit_road: true, laps_completed: 0, camera_car_idx: 0 }));
    assert.equal(o.text('bd-pit'), 'IN PIT');
    assert.ok(o.has('bd-pit', 'rah-status--warn'));
    assert.equal(o.text('bd-laps'), '0');
    assert.equal(o.text('bd-camera'), '0');
    o.update(payload({ on_pit_road: false }));
    assert.ok(!o.has('bd-pit', 'rah-status--warn'));
});

test('null values show as unavailable, never as zero or a made-up driver', () => {
    const o = loadOverlay();
    o.update(payload(UNKNOWN_FIELDS));
    assert.equal(o.text('bd-name'), UNAVAILABLE);
    for (const id of ['bd-number', 'bd-class', 'bd-position', 'bd-class-position', 'bd-laps',
        'bd-last', 'bd-best', 'bd-pit', 'bd-session']) {
        assert.equal(o.text(id), UNAVAILABLE, id);
    }
    assert.equal(o.text('bd-status'), 'Live');
});

test('a camera car missing from the roster says its identity is unavailable', () => {
    const o = loadOverlay();
    o.update(payload({ ...UNKNOWN_FIELDS, identity_available: false, camera_car_idx: 9 }));
    assert.equal(o.text('bd-name'), 'Identity unavailable');
    assert.equal(o.text('bd-number'), UNAVAILABLE);
    assert.equal(o.text('bd-camera'), '9');
    // Even if stale identity fields arrive, an unavailable identity is not drawn.
    o.update(payload({ identity_available: false, camera_car_idx: 9 }));
    assert.equal(o.text('bd-name'), 'Identity unavailable');
    assert.equal(o.text('bd-number'), UNAVAILABLE);
    assert.equal(o.text('bd-class'), UNAVAILABLE);
});

test('a camera switch replaces the card even when the new payload is incomplete', () => {
    const o = loadOverlay();
    o.update(payload());
    o.update({ available: true, camera_car_idx: 5, identity_available: true });
    assert.equal(o.text('bd-camera'), '5');
    for (const id of ['bd-number', 'bd-name', 'bd-class', 'bd-position', 'bd-class-position',
        'bd-laps', 'bd-last', 'bd-best', 'bd-pit', 'bd-session']) {
        assert.equal(o.text(id), UNAVAILABLE, id);
    }
    o.update(payload());
    o.update(payload({ ...UNKNOWN_FIELDS, identity_available: false, camera_car_idx: 6 }));
    assert.equal(o.text('bd-name'), 'Identity unavailable');
    assert.equal(o.text('bd-last'), UNAVAILABLE);
    assert.equal(o.text('bd-best'), UNAVAILABLE);
    assert.ok(!o.has('bd-pit', 'rah-status--warn'));
});

test('an unavailable camera clears the card and explains why', () => {
    const o = loadOverlay();
    o.update(payload());
    o.update(payload({ available: false, reason: 'camera_unavailable', camera_car_idx: null }));
    for (const id of IDS) assert.equal(o.text(id), UNAVAILABLE, id);
    assert.match(o.text('bd-status'), /no camera target/i);
    assert.ok(o.has('bd-status', 'rah-status--warn'));

    o.update(payload());
    o.update(payload({ available: false, reason: 'camera_target_excluded', camera_car_idx: null }));
    for (const id of IDS) assert.equal(o.text(id), UNAVAILABLE, id);
    assert.match(o.text('bd-status'), /pace car|spectator/i);
});

test('numbers and flags are guarded: only finite whole ranks, positive lap times, real booleans', () => {
    const o = loadOverlay();
    o.update(payload({
        position: 1.5, class_position: 0, laps_completed: -1, last_lap_s: NaN, best_lap_s: Infinity,
        on_pit_road: 'yes', camera_car_idx: '2',
    }));
    for (const id of ['bd-position', 'bd-class-position', 'bd-laps', 'bd-last', 'bd-best', 'bd-pit', 'bd-camera']) {
        assert.equal(o.text(id), UNAVAILABLE, id);
    }
    o.update(payload({ position: '3', laps_completed: true, last_lap_s: '88.2', best_lap_s: 0, on_pit_road: 1 }));
    for (const id of ['bd-position', 'bd-laps', 'bd-last', 'bd-best', 'bd-pit']) {
        assert.equal(o.text(id), UNAVAILABLE, id);
    }
});

test('hostile metadata is written with textContent only', () => {
    const hostile = '<img src=x onerror=alert(1)>';
    const o = loadOverlay();
    o.update(payload({ name: hostile, car_number: hostile, class_name: hostile, session_type: hostile }));
    assert.equal(o.text('bd-name'), hostile);
    assert.equal(o.text('bd-class'), hostile);
    for (const el of Object.values(o.elements)) assert.equal(el.innerHTML, '');
    o.update(payload({ name: 7, car_number: 7, class_name: {}, session_type: [] }));
    assert.equal(o.text('bd-name'), UNAVAILABLE);
    assert.equal(o.text('bd-number'), UNAVAILABLE);
    const source = fs.readFileSync(path.join(repoRoot, 'src/overlays/broadcast_driver/static/broadcast_driver.js'), 'utf8');
    assert.doesNotMatch(source, /innerHTML|insertAdjacentHTML|document\.write/);
});

test('clears on disconnect, connect_error, null payloads and 3s of silence', () => {
    for (const event of ['disconnect', 'connect_error']) {
        const o = loadOverlay();
        o.update(payload());
        o.handlers[event]();
        for (const id of IDS) assert.equal(o.text(id), UNAVAILABLE, `${event} ${id}`);
        assert.match(o.text('bd-status'), /disconnected/i);
        assert.ok(o.has('bd-status', 'rah-status--bad'));
    }

    const o = loadOverlay();
    o.update(payload());
    assert.equal(o.intervals.length, 1, 'one local stale timer');
    o.clock.now += 1000;
    o.intervals[0].fn();
    assert.equal(o.text('bd-name'), 'Bob', 'fresh data survives the timer');
    o.clock.now += 10000;
    o.intervals[0].fn();
    assert.equal(o.text('bd-name'), UNAVAILABLE);
    assert.match(o.text('bd-status'), /stale/i);

    o.handlers.connect();
    assert.match(o.text('bd-status'), /waiting/i);

    for (const bad of [null, undefined, [], 'text', 7]) {
        o.update(payload());
        o.update(bad);
        assert.equal(o.text('bd-name'), UNAVAILABLE, String(bad));
        assert.match(o.text('bd-status'), /no data/i);
    }
});

test('both themes render exactly the same data', () => {
    const original = loadOverlay({ theme: 'original' });
    const glass = loadOverlay({ theme: 'glass' });
    original.update(payload());
    glass.update(payload());
    assert.deepEqual(glass.snapshot(), original.snapshot());
    assert.ok(Object.keys(glass.snapshot()).length > 8, 'must render several elements');
});

test('page follows the overlay conventions and defines every id it uses', () => {
    const dir = 'src/overlays/broadcast_driver';
    const html = fs.readFileSync(path.join(repoRoot, dir, 'broadcast_driver.html'), 'utf8');
    assert.match(html, /overlay-theme\.css/);
    assert.match(html, /overlay_theme\.js/);
    assert.match(html, /socket\.io\.min\.js/);
    assert.ok(html.indexOf('broadcast_driver.css') < html.indexOf('overlay-theme.css'),
        'theme stylesheet must load after the base stylesheet');
    assert.match(html, /rah-card/);
    assert.match(html, /rah-metric/);
    assert.match(html, /pywebview-drag-region/);

    const js = fs.readFileSync(path.join(repoRoot, dir, 'static', 'broadcast_driver.js'), 'utf8');
    const ids = [...js.matchAll(/getElementById\('([\w-]+)'\)/g)].map((m) => m[1]);
    assert.ok(ids.length >= 9, 'script must look up its elements by id');
    for (const id of ids) {
        assert.match(html, new RegExp(`id="${id}"`), `broadcast_driver.html must define #${id}`);
    }

    const properties = JSON.parse(fs.readFileSync(path.join(repoRoot, dir, 'properties.json'), 'utf8'));
    assert.equal(properties.name, 'broadcast_driver');
    assert.ok(properties.display_name && properties.description);
    assert.ok(properties.resolution.width > 0 && properties.resolution.height > 0);

    const css = fs.readFileSync(path.join(repoRoot, dir, 'static', 'broadcast_driver.css'), 'utf8');
    assert.doesNotMatch(css, /data-rah-theme/, 'theme overrides live in the shared stylesheet only');
    assert.match(css, /background:\s*rgba\(0,\s*0,\s*0,\s*0\)/);
    assert.match(css, /\.rah-grid\.bd-grid/);
});

test('page and script state the camera-vs-player restriction and read no player metrics', () => {
    const dir = path.join(repoRoot, 'src/overlays/broadcast_driver');
    const html = fs.readFileSync(path.join(dir, 'broadcast_driver.html'), 'utf8');
    assert.match(html, /broadcast camera/i);
    assert.match(html, /never shown as this driver/i);
    const js = fs.readFileSync(path.join(dir, 'static', 'broadcast_driver.js'), 'utf8');
    assert.doesNotMatch(js, /\b(speed|throttle|brake|clutch|steering|rpm|gear|fuel)\b/i);
});

test('docs describe routes, event, payload, sources, restriction, no automation and live validation', () => {
    const docs = fs.readFileSync(path.join(repoRoot, 'docs/broadcast-driver.md'), 'utf8');
    for (const pattern of [
        /\/overlay\/broadcast_driver/, /broadcast_driver_update/, /broadcast_driver_data/,
        /CamCarIdx/, /PlayerCarIdx/, /DriverInfo/, /CarIdxPosition/, /CarIdxLastLapTime/,
        /CarIdxOnPitRoad/, /camera_unavailable/, /camera_target_excluded/, /pace car/i, /spectator/i,
        /never (shown|published)|not shown/i, /no automation|never sends commands/i, /live validation/i,
    ]) {
        assert.match(docs, pattern);
    }
});
