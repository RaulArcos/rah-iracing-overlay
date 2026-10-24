'use strict';

// Battle/Pace and Multiclass Standings front-end tests (T4, S2-S5).
// Runs the real overlay scripts against a stub DOM via node:vm and asserts
// the rendered text/classes. Uses only the Node built-in test runner.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const repoRoot = path.resolve(__dirname, '..');
const UNAVAILABLE = '--';

function makeElement(id) {
    const classes = new Set();
    let text = '';
    const el = {
        id,
        innerHTML: '',
        children: [],
        classes,
        classList: {
            add(name) { classes.add(name); },
            remove(name) { classes.delete(name); },
            toggle(name, force) {
                const on = force === undefined ? !classes.has(name) : Boolean(force);
                if (on) classes.add(name); else classes.delete(name);
            },
        },
        appendChild(child) { el.children.push(child); return child; },
    };
    Object.defineProperty(el, 'textContent', {
        get: () => text,
        set: (value) => { text = String(value); el.children.length = 0; },
    });
    Object.defineProperty(el, 'className', {
        get: () => [...classes].join(' '),
        set: (value) => { classes.clear(); String(value).split(/\s+/).filter(Boolean).forEach((c) => classes.add(c)); },
    });
    return el;
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
        createElement: () => makeElement(null),
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
    const tree = (el) => [el.textContent, [...el.classes].sort(), el.children.map(tree)];
    const snapshot = () => Object.fromEntries(Object.entries(elements).map(([id, el]) => [id, tree(el)]));
    return { elements, handlers, intervals, clock, ioCall, text, snapshot };
}

// ---- payload factories (mirror the backend schema) ---------------------

function standingsCar(overrides = {}) {
    return {
        car_idx: 1, position: 4, class_position: 2, car_number: '21', name: 'Ada',
        laps_completed: 4, best_lap_s: 90.5, last_lap_s: 91.0, best_lap_delta_s: 0.5,
        on_pit_road: false, is_player: false,
        gap_to_leader_s: 11.0, laps_down: 0, interval_s: 2.9,
        ...overrides,
    };
}

function standingsPayload(overrides = {}) {
    return {
        session_type: 'Race', gap_basis: 'race_f2time', player_car_idx: 1,
        classes: [
            { class_id: 200, class_name: 'LMP2', known: true, cars: [
                standingsCar({ car_idx: 2, position: 1, class_position: 1, car_number: '7', name: 'Bob',
                    laps_completed: 5, best_lap_s: 80.0, last_lap_s: 80.5, best_lap_delta_s: 0,
                    gap_to_leader_s: 0, interval_s: null }),
                standingsCar({ car_idx: 4, position: 2, class_position: 2, car_number: '9', name: 'Dan',
                    laps_completed: 5, best_lap_s: 80.4, last_lap_s: 81.0, gap_to_leader_s: 3.2, interval_s: 3.2 }),
            ] },
            { class_id: 100, class_name: 'GT3', known: true, cars: [
                standingsCar({ car_idx: 1, is_player: true }),
                standingsCar({ car_idx: 6, position: 6, class_position: 4, car_number: '5', name: 'Eve',
                    laps_completed: 3, best_lap_s: 92.0, last_lap_s: 93.0, on_pit_road: true,
                    gap_to_leader_s: null, laps_down: 2, interval_s: null }),
            ] },
        ],
        ...overrides,
    };
}

function pace(overrides = {}) {
    return { laps: 3, avg_lap_s: 90.8, trend_s_per_lap: -0.2, trend: 'improving', ...overrides };
}

function battleEntry(overrides = {}) {
    return {
        car_idx: 1, name: 'Ada', car_number: '21', position: 4, class_position: 2, laps_completed: 4,
        last_lap_s: 91.0, best_lap_s: 90.5, on_pit_road: false, laps_down: 0, pace: pace(),
        ...overrides,
    };
}

function battlePayload(overrides = {}) {
    return {
        session_type: 'Race', gap_basis: 'race_f2time', context: 'ok', class_id: 100, class_name: 'GT3',
        lap_time_source: 'CarIdxLastLapTime/CarIdxBestLapTime',
        player: battleEntry(),
        ahead: battleEntry({ car_idx: 5, name: 'Fay', car_number: '3', position: 3, class_position: 1,
            last_lap_s: 90.4, best_lap_s: 90.0, gap_s: 2.9, last_lap_delta_s: -0.6, best_lap_delta_s: -0.5,
            pace_delta_s: -0.5, pace: pace({ avg_lap_s: 90.3, trend_s_per_lap: -0.1 }) }),
        behind: battleEntry({ car_idx: 3, name: 'Cyd', car_number: '44', position: 5, class_position: 3,
            last_lap_s: 92.0, best_lap_s: 91.0, gap_s: 4.5, last_lap_delta_s: 1.0, best_lap_delta_s: 0.5,
            pace_delta_s: null, pace: pace({ laps: 0, avg_lap_s: null, trend_s_per_lap: null, trend: null }) }),
        ...overrides,
    };
}

const SHARED_FIELDS = ['name', 'pos', 'last', 'best', 'pace', 'trend'];
const COMPARE_FIELDS = ['gap', 'dlast', 'dbest', 'dpace'];
const BATTLE_IDS = [
    ...['ahead', 'player', 'behind'].flatMap((role) => SHARED_FIELDS.map((f) => `bp-${role}-${f}`)),
    ...['ahead', 'behind'].flatMap((role) => COMPARE_FIELDS.map((f) => `bp-${role}-${f}`)),
    'bp-status', 'bp-class', 'bp-basis',
];

function rows(o) {
    return o.elements['st-groups'].children;
}

function cells(row) {
    return row.children.map((cell) => cell.textContent);
}

// ---- standings ----------------------------------------------------------

test('standings joins its namespace with unbounded reconnection', () => {
    const { ioCall } = loadOverlay('standings');
    assert.equal(ioCall.namespace, '/standings');
    assert.equal(ioCall.options.reconnection, true);
    assert.equal(ioCall.options.reconnectionAttempts, Infinity);
});

test('standings renders class groups with ranks, identity, times and gaps', () => {
    const o = loadOverlay('standings');
    o.handlers.standings_update(standingsPayload());
    const groups = rows(o);
    assert.equal(groups.length, 2);
    assert.match(groups[0].children[0].textContent, /LMP2/);
    assert.match(groups[1].children[0].textContent, /GT3/);
    const [leader, second] = groups[0].children.slice(1);
    assert.deepEqual(cells(leader), ['P1', 'C1', '#7', 'Bob', 'L5', '1:20.000', '1:20.500', 'LEADER', '--', '']);
    assert.deepEqual(cells(second), ['P2', 'C2', '#9', 'Dan', 'L5', '1:20.400', '1:21.000', '+3.200', '+3.200', '']);
    const [ada, eve] = groups[1].children.slice(1);
    assert.deepEqual(cells(ada), ['P4', 'C2', '#21', 'Ada', 'L4', '1:30.500', '1:31.000', '+11.000', '+2.900', '']);
    assert.ok(ada.classes.has('st-row--player'));
    assert.ok(!second.classes.has('st-row--player'));
    assert.ok(ada.classes.has('rah-row'));
    assert.deepEqual(cells(eve), ['P6', 'C4', '#5', 'Eve', 'L3', '1:32.000', '1:33.000', '+2L', '--', 'PIT']);
    assert.equal(o.text('st-status'), 'Live');
    assert.match(o.text('st-session'), /Race/);
    assert.match(o.text('st-basis'), /F2Time/);
});

test('standings shows unavailable values instead of zero and keeps real zeroes', () => {
    const o = loadOverlay('standings');
    const bare = standingsCar({
        position: null, class_position: null, car_number: null, name: null, laps_completed: null,
        best_lap_s: null, last_lap_s: null, gap_to_leader_s: null, laps_down: null, interval_s: null,
        on_pit_road: null,
    });
    o.handlers.standings_update(standingsPayload({
        gap_basis: null,
        classes: [{ class_id: null, class_name: null, known: false, cars: [
            bare, standingsCar({ laps_completed: 0, interval_s: 0, gap_to_leader_s: 0.0, position: 2 })] }],
    }));
    const [unknown, zero] = rows(o)[0].children.slice(1);
    assert.deepEqual(cells(unknown), Array(9).fill(UNAVAILABLE).concat(['']));
    assert.equal(cells(zero)[4], 'L0');
    assert.equal(cells(zero)[8], '+0.000');
    assert.match(rows(o)[0].children[0].textContent, /unknown class/i);
    assert.match(o.text('st-basis'), /unavailable/i);
});

test('standings guards nonfinite numbers and malformed entries', () => {
    const o = loadOverlay('standings');
    o.handlers.standings_update(standingsPayload({
        classes: [{ class_id: 100, class_name: 'GT3', known: true, cars: [
            standingsCar({ best_lap_s: NaN, last_lap_s: Infinity, interval_s: 'x', gap_to_leader_s: -Infinity,
                position: 'P1', laps_completed: NaN }),
            null, 7, 'x',
        ] }, null, { cars: 'x' }],
    }));
    assert.equal(rows(o).length, 1);
    const cars = rows(o)[0].children.slice(1);
    assert.equal(cars.length, 1);
    assert.deepEqual(cells(cars[0]).slice(0, 1).concat(cells(cars[0]).slice(4, 9)), Array(6).fill(UNAVAILABLE));
});

test('standings limits long classes to the top cars plus the player and neighbours', () => {
    const o = loadOverlay('standings');
    const cars = Array.from({ length: 20 }, (_, i) => standingsCar({
        car_idx: i, position: i + 1, class_position: i + 1, name: `Driver ${i + 1}`, is_player: i === 14 }));
    o.handlers.standings_update(standingsPayload({
        classes: [{ class_id: 100, class_name: 'GT3', known: true, cars }] }));
    const shown = rows(o)[0].children.slice(1).map((row) => cells(row)[3]);
    assert.ok(shown.length <= 8);
    assert.deepEqual(shown.slice(-3), ['Driver 14', 'Driver 15', 'Driver 16']);
    assert.ok(shown.includes('Driver 1'));
    assert.match(rows(o)[0].children[0].textContent, /\b8\b.*\b20\b/);
});

test('standings treats null and malformed payloads as unavailable', () => {
    const o = loadOverlay('standings');
    for (const bad of [null, undefined, 'x', 7, [], { classes: 'x' }]) {
        o.handlers.standings_update(standingsPayload());
        o.handlers.standings_update(bad);
        assert.equal(rows(o).length, 0);
        assert.match(o.text('st-status'), /no data/i);
    }
    o.handlers.standings_update(standingsPayload({ classes: [] }));
    assert.equal(rows(o).length, 0);
    assert.match(o.text('st-status'), /no cars/i);
});

test('standings clears stale data on disconnect, connect_error and silence', () => {
    for (const event of ['disconnect', 'connect_error']) {
        const o = loadOverlay('standings');
        o.handlers.standings_update(standingsPayload());
        assert.equal(rows(o).length, 2);
        o.handlers[event]();
        assert.equal(rows(o).length, 0, event);
        assert.equal(o.text('st-session'), UNAVAILABLE);
        assert.match(o.text('st-status'), /disconnected/i);
    }
    const o = loadOverlay('standings');
    o.handlers.standings_update(standingsPayload());
    assert.equal(o.intervals.length, 1, 'one local stale timer');
    assert.equal(o.intervals[0].ms, 1000);
    o.clock.now += 1000;
    o.intervals[0].fn();
    assert.equal(rows(o).length, 2, 'fresh data survives the timer');
    o.clock.now += 10000;
    o.intervals[0].fn();
    assert.equal(rows(o).length, 0);
    assert.match(o.text('st-status'), /stale|no data/i);
    o.handlers.connect();
    assert.match(o.text('st-status'), /waiting/i);
});

test('standings sets hostile metadata via textContent only', () => {
    const o = loadOverlay('standings');
    const hostile = '<img src=x onerror=alert(1)>';
    o.handlers.standings_update(standingsPayload({
        session_type: hostile,
        classes: [{ class_id: 1, class_name: hostile, known: true, cars: [
            standingsCar({ name: hostile, car_number: hostile })] }],
    }));
    assert.equal(cells(rows(o)[0].children[1])[3], hostile);
    assert.match(rows(o)[0].children[0].textContent, /<img/);
    assert.equal(o.elements['st-groups'].innerHTML, '');
    for (const row of rows(o)[0].children) {
        assert.equal(row.innerHTML, '');
    }
    const source = fs.readFileSync(path.join(repoRoot, 'src/overlays/standings/static/standings.js'), 'utf8');
    assert.doesNotMatch(source, /innerHTML|insertAdjacentHTML|document\.write/);
});

// ---- battle / pace ------------------------------------------------------

test('battle overlay joins its namespace with unbounded reconnection', () => {
    const { ioCall } = loadOverlay('battle_pace');
    assert.equal(ioCall.namespace, '/battle_pace');
    assert.equal(ioCall.options.reconnection, true);
    assert.equal(ioCall.options.reconnectionAttempts, Infinity);
});

test('battle overlay renders ahead, player and behind with signed comparisons', () => {
    const o = loadOverlay('battle_pace');
    o.handlers.battle_pace_update(battlePayload());
    assert.equal(o.text('bp-ahead-name'), 'Fay');
    assert.equal(o.text('bp-ahead-pos'), 'P3 · C1');
    assert.equal(o.text('bp-ahead-gap'), '-2.900');
    assert.equal(o.text('bp-ahead-last'), '1:30.400');
    assert.equal(o.text('bp-ahead-best'), '1:30.000');
    assert.equal(o.text('bp-ahead-dlast'), '-0.600');
    assert.equal(o.text('bp-ahead-dbest'), '-0.500');
    assert.equal(o.text('bp-ahead-dpace'), '-0.500');
    assert.equal(o.text('bp-ahead-pace'), '1:30.300');
    assert.match(o.text('bp-ahead-trend'), /improving/i);
    assert.match(o.text('bp-ahead-trend'), /-0\.100/);
    assert.equal(o.text('bp-player-name'), 'Ada');
    assert.equal(o.text('bp-player-pos'), 'P4 · C2');
    assert.equal(o.text('bp-behind-name'), 'Cyd');
    assert.equal(o.text('bp-behind-gap'), '+4.500');
    assert.equal(o.text('bp-behind-dlast'), '+1.000');
    assert.equal(o.text('bp-behind-dpace'), UNAVAILABLE);
    assert.equal(o.text('bp-behind-pace'), UNAVAILABLE);
    assert.equal(o.text('bp-behind-trend'), UNAVAILABLE);
    assert.equal(o.text('bp-class'), 'GT3');
    assert.equal(o.text('bp-status'), 'Live');
    assert.match(o.text('bp-basis'), /F2Time/);
});

test('battle overlay colours an edge only for real deltas', () => {
    const o = loadOverlay('battle_pace');
    const has = (id, name) => o.elements[id].classes.has(name);
    o.handlers.battle_pace_update(battlePayload());
    assert.ok(has('bp-ahead-dlast', 'rah-status--warn'), 'faster car ahead is a threat');
    assert.ok(has('bp-behind-dlast', 'rah-status--ok'), 'slower car behind is an edge');
    o.handlers.battle_pace_update(battlePayload({
        ahead: battleEntry({ gap_s: 0, last_lap_delta_s: 0, best_lap_delta_s: null, pace_delta_s: null }),
        behind: battleEntry({ gap_s: null, last_lap_delta_s: null, best_lap_delta_s: null, pace_delta_s: null }),
    }));
    for (const id of ['bp-ahead-dlast', 'bp-ahead-dbest', 'bp-behind-dlast', 'bp-behind-dbest', 'bp-behind-dpace']) {
        assert.ok(!has(id, 'rah-status--ok') && !has(id, 'rah-status--warn') && !has(id, 'rah-status--bad'), id);
    }
    assert.equal(o.text('bp-ahead-dlast'), '0.000');
    assert.equal(o.text('bp-ahead-gap'), '0.000');
    assert.equal(o.text('bp-behind-gap'), UNAVAILABLE);
    assert.equal(o.text('bp-behind-dlast'), UNAVAILABLE);
});

test('battle overlay never invents a same-class comparison', () => {
    const o = loadOverlay('battle_pace');
    const contexts = {
        class_unknown: /class unknown/i,
        class_position_unavailable: /class position/i,
        player_unavailable: /player/i,
    };
    for (const [context, pattern] of Object.entries(contexts)) {
        o.handlers.battle_pace_update(battlePayload({
            context, class_id: null, class_name: null, ahead: null, behind: null,
            player: context === 'player_unavailable' ? null : battleEntry(),
        }));
        for (const id of BATTLE_IDS.filter((i) => /ahead|behind/.test(i))) {
            assert.equal(o.text(id), UNAVAILABLE, `${context} ${id}`);
        }
        assert.match(o.text('bp-status'), pattern, context);
        assert.ok(o.elements['bp-status'].classes.has('rah-status--warn'));
        assert.equal(o.text('bp-class'), UNAVAILABLE);
    }
    assert.equal(o.text('bp-player-name'), UNAVAILABLE);
});

test('battle overlay falls back to the number and never invents a name', () => {
    const o = loadOverlay('battle_pace');
    o.handlers.battle_pace_update(battlePayload({
        ahead: battleEntry({ name: null, car_number: '3', gap_s: 1 }),
        behind: battleEntry({ name: null, car_number: null, gap_s: 1 }),
    }));
    assert.equal(o.text('bp-ahead-name'), '#3');
    assert.equal(o.text('bp-behind-name'), UNAVAILABLE);
});

test('battle overlay guards nonfinite numbers and treats malformed payloads as unavailable', () => {
    const o = loadOverlay('battle_pace');
    o.handlers.battle_pace_update(battlePayload({
        ahead: battleEntry({ gap_s: NaN, last_lap_s: Infinity, last_lap_delta_s: 'x', best_lap_s: -Infinity,
            pace: { laps: NaN, avg_lap_s: NaN, trend_s_per_lap: Infinity, trend: 'sideways' } }),
    }));
    for (const id of ['bp-ahead-gap', 'bp-ahead-last', 'bp-ahead-dlast', 'bp-ahead-best', 'bp-ahead-pace',
        'bp-ahead-trend']) {
        assert.equal(o.text(id), UNAVAILABLE, id);
    }
    for (const bad of [null, undefined, 'x', 7, []]) {
        o.handlers.battle_pace_update(battlePayload());
        o.handlers.battle_pace_update(bad);
        for (const id of BATTLE_IDS.filter((i) => i !== 'bp-status' && i !== 'bp-basis')) {
            assert.equal(o.text(id), UNAVAILABLE, id);
        }
        assert.match(o.text('bp-status'), /no data/i);
    }
});

test('battle overlay clears stale data on disconnect, connect_error and silence', () => {
    for (const event of ['disconnect', 'connect_error']) {
        const o = loadOverlay('battle_pace');
        o.handlers.battle_pace_update(battlePayload());
        o.handlers[event]();
        assert.equal(o.text('bp-ahead-name'), UNAVAILABLE, event);
        assert.equal(o.text('bp-player-pos'), UNAVAILABLE, event);
        assert.match(o.text('bp-status'), /disconnected/i);
    }
    const o = loadOverlay('battle_pace');
    o.handlers.battle_pace_update(battlePayload());
    assert.equal(o.intervals.length, 1, 'one local stale timer');
    o.clock.now += 1000;
    o.intervals[0].fn();
    assert.equal(o.text('bp-ahead-name'), 'Fay', 'fresh data survives the timer');
    o.clock.now += 10000;
    o.intervals[0].fn();
    assert.equal(o.text('bp-ahead-name'), UNAVAILABLE);
    assert.match(o.text('bp-status'), /stale|no data/i);
    o.handlers.connect();
    assert.match(o.text('bp-status'), /waiting/i);
});

test('battle overlay sets hostile metadata via textContent only', () => {
    const o = loadOverlay('battle_pace');
    const hostile = '<img src=x onerror=alert(1)>';
    o.handlers.battle_pace_update(battlePayload({ class_name: hostile, ahead: battleEntry({ name: hostile }) }));
    assert.equal(o.text('bp-ahead-name'), hostile);
    assert.equal(o.text('bp-class'), hostile);
    for (const el of Object.values(o.elements)) {
        assert.equal(el.innerHTML, '');
    }
    const source = fs.readFileSync(path.join(repoRoot, 'src/overlays/battle_pace/static/battle_pace.js'), 'utf8');
    assert.doesNotMatch(source, /innerHTML|insertAdjacentHTML|document\.write/);
});

// ---- both themes, conventions, docs ------------------------------------

test('both themes render exactly the same data', () => {
    for (const [name, event, payload] of [
        ['standings', 'standings_update', standingsPayload()],
        ['battle_pace', 'battle_pace_update', battlePayload()],
    ]) {
        const original = loadOverlay(name, { theme: 'original' });
        const glass = loadOverlay(name, { theme: 'glass' });
        original.handlers[event](payload);
        glass.handlers[event](payload);
        assert.deepEqual(glass.snapshot(), original.snapshot(), name);
        assert.ok(Object.keys(glass.snapshot()).length >= 3, `${name} must render several elements`);
    }
});

for (const name of ['battle_pace', 'standings']) {
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
        const literalIds = [...js.matchAll(/getElementById\('([\w-]+)'\)/g)].map((m) => m[1]);
        const ids = name === 'battle_pace' ? BATTLE_IDS.concat(literalIds) : literalIds;
        assert.ok(ids.length >= 4, 'script must look up its elements by id');
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
    for (const name of ['battle_pace', 'standings']) {
        const css = fs.readFileSync(path.join(repoRoot, `src/overlays/${name}/static/${name}.css`), 'utf8');
        assert.doesNotMatch(css, /data-rah-theme/, 'theme overrides live in the shared stylesheet only');
        assert.match(css, /background:\s*rgba\(0,\s*0,\s*0,\s*0\)/);
    }
});

test('battle & standings docs describe routes, units, signs, provenance and live validation', () => {
    const docs = fs.readFileSync(path.join(repoRoot, 'docs/battle-standings.md'), 'utf8');
    for (const pattern of [
        /\/overlay\/battle_pace/, /\/overlay\/standings/,
        /battle_pace_update/, /standings_update/,
        /CarIdxF2Time/, /CarIdxEstTime/, /CarClassID/, /CarIdxClassPosition/,
        /opponent minus (the )?player/i, /seconds/i, /laps_down/, /null/,
        /consecutive/i, /unknown class/i, /practice|qualif/i, /live validation/i,
    ]) {
        assert.match(docs, pattern);
    }
});
