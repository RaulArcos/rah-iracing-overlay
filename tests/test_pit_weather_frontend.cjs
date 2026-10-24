'use strict';

// Pit Assistant and Weather front-end tests (T5, S2-S5).
// Runs the real overlay scripts against a stub DOM via node:vm and asserts
// the rendered text/classes. Uses only the Node built-in test runner.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const repoRoot = path.resolve(__dirname, '..');
const UNAVAILABLE = '\u2014';
const OVERLAYS = {
    pit_assistant: { event: 'pit_assistant_update', status: 'pit-status', probe: 'pit-speed' },
    weather: { event: 'weather_update', status: 'wx-status', probe: 'wx-air' },
};

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
    const relativePath = `src/overlays/${name}/static/${name}.js`;
    vm.runInContext(fs.readFileSync(path.join(repoRoot, relativePath), 'utf8'), sandbox, { filename: relativePath });
    assert.ok(readyHandler, 'script must register a DOMContentLoaded handler');
    readyHandler();
    const text = (id) => elements[id].textContent;
    const has = (id, cls) => elements[id].classes.has(cls);
    const snapshot = () => Object.fromEntries(
        Object.entries(elements).map(([id, el]) => [id, [el.textContent, [...el.classes].sort()]]));
    return { elements, handlers, intervals, clock, ioCall, text, has, snapshot };
}

function pitPayload(overrides = {}) {
    return {
        speed_kmh: 57.6, on_pit_road: true, in_pit_stall: false, pits_open: true, service_active: false,
        pit_speed_limit_kmh: 60, pit_speed_limit_source: 'WeekendInfo.TrackPitSpeedLimit',
        pit_speed_margin_kmh: 2.4, pit_speed_state: 'within_limit',
        repair_left_s: 12.5, optional_repair_left_s: 0, tow_time_s: null,
        service_flags: ['lf_tire_change', 'fuel_fill'], service_flags_raw: 17,
        service_status: 'in_progress', service_status_code: 1,
        service_fuel_amount: 25.5, service_fuel_unit: 'L/kWh', service_fuel_requested: true,
        read_only: true,
        ...overrides,
    };
}

const EMPTY_PIT = {
    speed_kmh: null, on_pit_road: null, in_pit_stall: null, pits_open: null, service_active: null,
    pit_speed_limit_kmh: null, pit_speed_limit_source: null, pit_speed_margin_kmh: null,
    pit_speed_state: null, repair_left_s: null, optional_repair_left_s: null, tow_time_s: null,
    service_flags: null, service_flags_raw: null, service_status: null, service_status_code: null,
    service_fuel_amount: null, service_fuel_unit: 'L/kWh', service_fuel_requested: null,
};

function weatherPayload(overrides = {}) {
    return {
        air_temp_c: 21.5, track_temp_c: 33.5, humidity_pct: 55, wind_speed_ms: 3,
        wind_speed_kmh: 10.8, wind_dir_deg: 90, precipitation_pct: 0,
        track_wetness: 'dry', track_wetness_code: 1, declared_wet: false, observed: true,
        ...overrides,
    };
}

const EMPTY_WEATHER = {
    air_temp_c: null, track_temp_c: null, humidity_pct: null, wind_speed_ms: null,
    wind_speed_kmh: null, wind_dir_deg: null, precipitation_pct: null,
    track_wetness: null, track_wetness_code: null, declared_wet: null, observed: true,
};

const SAMPLE = { pit_assistant: pitPayload, weather: weatherPayload };
const PIT_IDS = ['pit-speed', 'pit-limit', 'pit-margin', 'pit-limit-state', 'pit-road', 'pit-stall',
    'pit-open', 'pit-service', 'pit-repair', 'pit-opt-repair', 'pit-tow', 'pit-flags',
    'pit-svstatus', 'pit-fuel'];
const WEATHER_IDS = ['wx-air', 'wx-track', 'wx-humidity', 'wx-wind', 'wx-wind-ms', 'wx-wind-dir',
    'wx-precip', 'wx-wetness', 'wx-declared'];

test('overlays join their dedicated namespaces with unbounded reconnection', () => {
    for (const name of Object.keys(OVERLAYS)) {
        const { ioCall } = loadOverlay(name);
        assert.equal(ioCall.namespace, `/${name}`);
        assert.equal(ioCall.options.reconnection, true);
        assert.equal(ioCall.options.reconnectionAttempts, Infinity);
    }
});

test('pit assistant renders speed, limit, margin and an in-limit status', () => {
    const o = loadOverlay('pit_assistant');
    o.handlers.pit_assistant_update(pitPayload());
    assert.equal(o.text('pit-speed'), '57.6');
    assert.equal(o.text('pit-limit'), '60.0');
    assert.equal(o.text('pit-margin'), '+2.4');
    assert.equal(o.text('pit-limit-state'), 'WITHIN LIMIT');
    assert.ok(o.has('pit-limit-state', 'rah-status--ok'));
    assert.equal(o.text('pit-road'), 'YES');
    assert.equal(o.text('pit-stall'), 'NO');
    assert.equal(o.text('pit-open'), 'YES');
    assert.equal(o.text('pit-service'), 'IDLE');
    assert.equal(o.text(OVERLAYS.pit_assistant.status), 'Live');
});

test('pit assistant warns in text, not colour alone, when over the limit or pits are closed', () => {
    const o = loadOverlay('pit_assistant');
    o.handlers.pit_assistant_update(pitPayload({
        speed_kmh: 72, pit_speed_margin_kmh: -12, pit_speed_state: 'over_limit', pits_open: false,
    }));
    assert.equal(o.text('pit-margin'), '-12.0');
    assert.equal(o.text('pit-limit-state'), 'OVER LIMIT');
    assert.ok(o.has('pit-limit-state', 'rah-status--bad'));
    assert.equal(o.text('pit-open'), 'CLOSED');
    assert.ok(o.has('pit-open', 'rah-status--warn'));
});

test('pit assistant keeps real zeroes and shows null as unavailable', () => {
    const o = loadOverlay('pit_assistant');
    o.handlers.pit_assistant_update(pitPayload({
        speed_kmh: 0, pit_speed_margin_kmh: 0, repair_left_s: 0, tow_time_s: 0,
        on_pit_road: false, service_flags: [], service_flags_raw: 0, service_status: 'none',
        service_status_code: 0, service_fuel_requested: false, service_fuel_amount: 0,
    }));
    assert.equal(o.text('pit-speed'), '0.0');
    assert.equal(o.text('pit-margin'), '0.0');
    assert.equal(o.text('pit-repair'), '0.0');
    assert.equal(o.text('pit-tow'), '0.0');
    assert.equal(o.text('pit-road'), 'NO');
    assert.equal(o.text('pit-flags'), 'NONE');
    assert.equal(o.text('pit-svstatus'), 'NONE');
    assert.equal(o.text('pit-fuel'), 'NOT REQUESTED');

    o.handlers.pit_assistant_update(EMPTY_PIT);
    for (const id of PIT_IDS) {
        assert.equal(o.text(id), UNAVAILABLE, id);
    }
});

test('pit assistant shows requested fuel with the SDK unit label, never invented liters', () => {
    const o = loadOverlay('pit_assistant');
    o.handlers.pit_assistant_update(pitPayload());
    assert.equal(o.text('pit-fuel'), '25.5 L/kWh');
    o.handlers.pit_assistant_update(pitPayload({ service_fuel_amount: 0, service_fuel_requested: true }));
    assert.equal(o.text('pit-fuel'), '0.0 L/kWh');
    const source = fs.readFileSync(path.join(repoRoot, 'src/overlays/pit_assistant/static/pit_assistant.js'), 'utf8');
    const html = fs.readFileSync(path.join(repoRoot, 'src/overlays/pit_assistant/pit_assistant.html'), 'utf8');
    assert.doesNotMatch(source + html, /liters|\bL\b(?!\/)/);
    assert.match(html, /requested/i);
});

test('pit assistant names service flags and status, and keeps unknown codes visible', () => {
    const o = loadOverlay('pit_assistant');
    o.handlers.pit_assistant_update(pitPayload());
    assert.equal(o.text('pit-flags'), 'LF TIRE CHANGE, FUEL FILL');
    assert.equal(o.text('pit-svstatus'), 'IN PROGRESS');
    o.handlers.pit_assistant_update(pitPayload({
        service_flags: [], service_flags_raw: 128, service_status: null, service_status_code: 55,
    }));
    assert.equal(o.text('pit-flags'), 'RAW 128');
    assert.equal(o.text('pit-svstatus'), 'CODE 55');
});

test('weather renders observed values with units and signed temperatures', () => {
    const o = loadOverlay('weather');
    o.handlers.weather_update(weatherPayload());
    assert.equal(o.text('wx-air'), '21.5');
    assert.equal(o.text('wx-track'), '33.5');
    assert.equal(o.text('wx-humidity'), '55%');
    assert.equal(o.text('wx-wind'), '10.8');
    assert.equal(o.text('wx-wind-ms'), '3.0 m/s');
    assert.equal(o.text('wx-wind-dir'), '90\u00b0');
    assert.equal(o.text('wx-precip'), '0.0%');
    assert.equal(o.text('wx-wetness'), 'DRY');
    assert.equal(o.text('wx-declared'), 'NO');
    assert.equal(o.text('wx-status'), 'Live');

    o.handlers.weather_update(weatherPayload({ air_temp_c: -4.5, track_temp_c: 0 }));
    assert.equal(o.text('wx-air'), '-4.5');
    assert.equal(o.text('wx-track'), '0.0');
});

test('weather keeps calm and dry zeroes real and null unavailable', () => {
    const o = loadOverlay('weather');
    o.handlers.weather_update(weatherPayload({
        wind_speed_ms: 0, wind_speed_kmh: 0, wind_dir_deg: 0, humidity_pct: 0, precipitation_pct: 0,
    }));
    assert.equal(o.text('wx-wind'), '0.0');
    assert.equal(o.text('wx-wind-dir'), '0\u00b0');
    assert.equal(o.text('wx-humidity'), '0%');

    o.handlers.weather_update(EMPTY_WEATHER);
    for (const id of WEATHER_IDS) {
        assert.equal(o.text(id), UNAVAILABLE, id);
    }
});

test('weather flags declared-wet in text and keeps unknown wetness codes visible', () => {
    const o = loadOverlay('weather');
    o.handlers.weather_update(weatherPayload({ declared_wet: true, track_wetness: 'very_wet', track_wetness_code: 6 }));
    assert.equal(o.text('wx-declared'), 'YES');
    assert.ok(o.has('wx-declared', 'rah-status--warn'));
    assert.equal(o.text('wx-wetness'), 'VERY WET');
    o.handlers.weather_update(weatherPayload({ track_wetness: null, track_wetness_code: 99 }));
    assert.equal(o.text('wx-wetness'), 'CODE 99');
});

test('overlays clear on disconnect, connect_error, null payloads and 3s of silence', () => {
    for (const [name, meta] of Object.entries(OVERLAYS)) {
        for (const event of ['disconnect', 'connect_error']) {
            const o = loadOverlay(name);
            o.handlers[meta.event](SAMPLE[name]());
            assert.notEqual(o.text(meta.probe), UNAVAILABLE);
            o.handlers[event]();
            assert.equal(o.text(meta.probe), UNAVAILABLE, `${name} ${event}`);
            assert.match(o.text(meta.status), /disconnected/i);
        }

        const o = loadOverlay(name);
        o.handlers[meta.event](SAMPLE[name]());
        assert.equal(o.intervals.length, 1, 'one local stale timer');
        o.clock.now += 1000;
        o.intervals[0].fn();
        assert.notEqual(o.text(meta.probe), UNAVAILABLE, 'fresh data survives the timer');
        o.clock.now += 10000;
        o.intervals[0].fn();
        assert.equal(o.text(meta.probe), UNAVAILABLE);
        assert.match(o.text(meta.status), /stale|no data/i);

        o.handlers.connect();
        assert.match(o.text(meta.status), /waiting/i);

        for (const bad of [null, undefined, [], 'text', 7]) {
            o.handlers[meta.event](SAMPLE[name]());
            o.handlers[meta.event](bad);
            assert.equal(o.text(meta.probe), UNAVAILABLE, `${name} ${String(bad)}`);
            assert.match(o.text(meta.status), /no data/i);
        }
    }
});

test('overlays set hostile metadata via textContent only and ignore non-finite numbers', () => {
    const hostile = '<img src=x onerror=alert(1)>';
    const pit = loadOverlay('pit_assistant');
    pit.handlers.pit_assistant_update(pitPayload({
        service_status: hostile, service_flags: [hostile], service_fuel_unit: hostile,
        speed_kmh: NaN, pit_speed_margin_kmh: Infinity, repair_left_s: '12', on_pit_road: 'yes',
    }));
    const wx = loadOverlay('weather');
    wx.handlers.weather_update(weatherPayload({
        track_wetness: hostile, air_temp_c: NaN, wind_speed_kmh: -Infinity, declared_wet: 'yes',
    }));
    for (const o of [pit, wx]) {
        for (const el of Object.values(o.elements)) {
            assert.equal(el.innerHTML, '');
        }
    }
    assert.equal(pit.text('pit-speed'), UNAVAILABLE);
    assert.equal(pit.text('pit-margin'), UNAVAILABLE);
    assert.equal(pit.text('pit-repair'), UNAVAILABLE);
    assert.equal(pit.text('pit-road'), UNAVAILABLE);
    assert.equal(wx.text('wx-air'), UNAVAILABLE);
    assert.equal(wx.text('wx-wind'), UNAVAILABLE);
    assert.equal(wx.text('wx-declared'), UNAVAILABLE);
    for (const name of Object.keys(OVERLAYS)) {
        const source = fs.readFileSync(path.join(repoRoot, `src/overlays/${name}/static/${name}.js`), 'utf8');
        assert.doesNotMatch(source, /innerHTML|insertAdjacentHTML|document\.write/);
    }
});

test('both themes render exactly the same data', () => {
    for (const [name, meta] of Object.entries(OVERLAYS)) {
        const original = loadOverlay(name, { theme: 'original' });
        const glass = loadOverlay(name, { theme: 'glass' });
        original.handlers[meta.event](SAMPLE[name]());
        glass.handlers[meta.event](SAMPLE[name]());
        assert.deepEqual(glass.snapshot(), original.snapshot(), name);
        assert.ok(Object.keys(glass.snapshot()).length > 8, `${name} must render several elements`);
    }
});

for (const name of Object.keys(OVERLAYS)) {
    test(`${name} page follows the overlay conventions and defines every id it uses`, () => {
        const dir = `src/overlays/${name}`;
        const html = fs.readFileSync(path.join(repoRoot, dir, `${name}.html`), 'utf8');
        assert.match(html, /overlay-theme\.css/);
        assert.match(html, /overlay_theme\.js/);
        assert.match(html, /socket\.io\.min\.js/);
        assert.ok(html.indexOf(`${name}.css`) < html.indexOf('overlay-theme.css'),
            'theme stylesheet must load after the base stylesheet');
        assert.match(html, /rah-card/);
        assert.match(html, /rah-metric/);
        assert.match(html, /pywebview-drag-region/);

        const js = fs.readFileSync(path.join(repoRoot, dir, 'static', `${name}.js`), 'utf8');
        const ids = [...js.matchAll(/getElementById\('([\w-]+)'\)/g)].map((m) => m[1]);
        assert.ok(ids.length >= 9, 'script must look up its elements by id');
        for (const id of ids) {
            assert.match(html, new RegExp(`id="${id}"`), `${name}.html must define #${id}`);
        }

        const properties = JSON.parse(fs.readFileSync(path.join(repoRoot, dir, 'properties.json'), 'utf8'));
        assert.equal(properties.name, name);
        assert.ok(properties.display_name && properties.description);
        assert.ok(properties.resolution.width > 0 && properties.resolution.height > 0);

        const css = fs.readFileSync(path.join(repoRoot, dir, 'static', `${name}.css`), 'utf8');
        assert.doesNotMatch(css, /data-rah-theme/, 'theme overrides live in the shared stylesheet only');
        assert.match(css, /background:\s*rgba\(0,\s*0,\s*0,\s*0\)/);
        // Loaded before the shared .rah-grid rule, so a layout override must
        // be a compound selector to win on specificity.
        assert.match(css, /\.rah-grid\.(pit|weather)-grid/);
    });
}

test('weather page states that values are observed, not forecast', () => {
    const html = fs.readFileSync(path.join(repoRoot, 'src/overlays/weather/weather.html'), 'utf8');
    assert.match(html, /observed/i);
    assert.match(html, /not a forecast/i);
});

test('pit & weather docs describe routes, units, availability, no automation and live limits', () => {
    const docs = fs.readFileSync(path.join(repoRoot, 'docs/pit-weather.md'), 'utf8');
    for (const pattern of [
        /\/overlay\/pit_assistant/, /\/overlay\/weather/,
        /pit_assistant_update/, /weather_update/,
        /TrackPitSpeedLimit/, /PitSvFuel/, /L\/kWh/, /TrackTempCrew/, /RelativeHumidity/,
        /WindDir/, /TrackWetness/, /observed/i, /not a forecast/i,
        /no automation|never sends commands/i, /live validation/i,
    ]) {
        assert.match(docs, pattern);
    }
});
