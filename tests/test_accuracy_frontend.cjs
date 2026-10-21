'use strict';

// Accuracy regression tests for the overlay front-end scripts (T1, S3-S5).
// Runs the real overlay JS against a stub DOM via node:vm, then asserts the
// rendered output. Uses only the Node built-in test runner.

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
        width: 320,
        height: 320,
        classes,
        classList: {
            toggle(name, force) {
                if (force === undefined) {
                    if (classes.has(name)) classes.delete(name);
                    else classes.add(name);
                } else if (force) {
                    classes.add(name);
                } else {
                    classes.delete(name);
                }
            },
        },
        getContext() {
            return this.ctx;
        },
        ctx: null,
    };
}

function makeCanvasContext() {
    const ops = [];
    const record = (name) => (...args) => ops.push({ name, args });
    return {
        ops,
        clearRect: record('clearRect'),
        beginPath: record('beginPath'),
        stroke: record('stroke'),
        fill: record('fill'),
        arc: record('arc'),
        moveTo: record('moveTo'),
        lineTo: record('lineTo'),
        lineWidth: 2,
        strokeStyle: '',
        fillStyle: '',
    };
}

function loadOverlayScript(relativePath) {
    const elements = {};
    let readyHandler = null;
    const handlers = {};
    const document = {
        addEventListener(event, handler) {
            if (event === 'DOMContentLoaded') readyHandler = handler;
        },
        getElementById(id) {
            if (!elements[id]) {
                elements[id] = makeElement(id);
                if (id.includes('canvas')) elements[id].ctx = makeCanvasContext();
            }
            return elements[id];
        },
    };
    const io = (namespace) => ({
        on(event, handler) {
            handlers[`${namespace}:${event}`] = handler;
        },
    });
    const sandbox = { document, io, console };
    vm.createContext(sandbox);
    const code = fs.readFileSync(path.join(repoRoot, relativePath), 'utf8');
    vm.runInContext(code, sandbox, { filename: relativePath });
    assert.ok(readyHandler, 'script must register a DOMContentLoaded handler');
    readyHandler();
    return { elements, handlers };
}

test('relative overlay marks cars ahead/behind with the correct row class', () => {
    const { elements, handlers } = loadOverlayScript('src/overlays/relative/static/relative.js');
    handlers['/relative:relative_update']({
        player_position: 3,
        cars: [
            { car_idx: 2, position: 2, car_number: '7', name: 'Bob', gap: 2.5, on_pit_road: false },
            { car_idx: 3, position: 4, car_number: '44', name: 'Cyd', gap: -1.2, on_pit_road: false },
        ],
    });
    const html = elements['relative-body'].innerHTML;
    const rows = html.split('<tr');
    const aheadRow = rows[1];
    const behindRow = rows[2];
    assert.match(aheadRow, /row-ahead/);
    assert.doesNotMatch(aheadRow, /row-behind/);
    assert.match(behindRow, /row-behind/);
    assert.doesNotMatch(behindRow, /row-ahead/);
});

test('relative overlay keeps iRacing sign convention and formats gap labels', () => {
    const { elements, handlers } = loadOverlayScript('src/overlays/relative/static/relative.js');
    handlers['/relative:relative_update']({
        player_position: 1,
        cars: [
            { car_idx: 2, position: 2, car_number: '7', name: 'Bob', gap: 2.5 },
            { car_idx: 3, position: 3, car_number: '44', name: 'Cyd', gap: -1.2, on_pit_road: true },
        ],
    });
    const html = elements['relative-body'].innerHTML;
    assert.match(html, /\+2\.50s/);
    assert.match(html, /-1\.20s/);
    assert.match(html, /row-pit/);
    assert.equal(elements['player-pos'].textContent, 'P1');
});

test('relative overlay marks estimated gaps explicitly', () => {
    const { elements, handlers } = loadOverlayScript('src/overlays/relative/static/relative.js');
    handlers['/relative:relative_update']({
        player_position: 1,
        cars: [
            { car_idx: 2, position: 2, car_number: '7', name: 'Bob', gap: 2.5, gap_is_estimate: true },
        ],
    });
    assert.match(elements['relative-body'].innerHTML, /~\+2\.50s/);
});

test('relative overlay renders legacy payloads without estimate marker unchanged', () => {
    const { elements, handlers } = loadOverlayScript('src/overlays/relative/static/relative.js');
    handlers['/relative:relative_update']({
        player_position: 1,
        cars: [{ car_idx: 2, position: 2, car_number: '7', name: 'Bob', gap: 2.5 }],
    });
    assert.match(elements['relative-body'].innerHTML, /\+2\.50s/);
    assert.doesNotMatch(elements['relative-body'].innerHTML, /~/);
});

test('radar overlay derives meters from the provided track length', () => {
    const { elements, handlers } = loadOverlayScript('src/overlays/radar/static/radar.js');
    handlers['/radar:radar_update']({
        left_alert: false,
        right_alert: true,
        track_length_m: 5891,
        nearby: [
            { car_idx: 2, distance_pct: 0.02, relation: 'ahead' },
            { car_idx: 3, distance_pct: -0.01, relation: 'behind' },
        ],
    });
    assert.equal(elements['left-alert'].classes.has('active'), false);
    assert.equal(elements['right-alert'].classes.has('active'), true);
    const html = elements['nearby-list'].innerHTML;
    assert.match(html, /Car 2/);
    assert.match(html, /AHEAD 118m/);
    assert.match(html, /Car 3/);
    assert.match(html, /BEHIND 59m/);
});

test('radar overlay shows no invented meters when track length is unavailable', () => {
    const { elements, handlers } = loadOverlayScript('src/overlays/radar/static/radar.js');
    handlers['/radar:radar_update']({
        left_alert: false,
        right_alert: false,
        nearby: [{ car_idx: 2, distance_pct: 0.02, relation: 'ahead' }],
    });
    const html = elements['nearby-list'].innerHTML;
    assert.match(html, /AHEAD/);
    assert.doesNotMatch(html, /\d+m/);
    assert.doesNotMatch(html, /5500/);

    handlers['/radar:radar_update']({
        track_length_m: 0,
        nearby: [{ car_idx: 2, distance_pct: 0.02, relation: 'behind' }],
    });
    assert.doesNotMatch(elements['nearby-list'].innerHTML, /\d+m/);
});

test('laptime graph skips non-finite history points', () => {
    const { elements, handlers } = loadOverlayScript('src/overlays/laptime_graph/static/laptime_graph.js');
    handlers['/laptime_graph:laptime_graph_update']({
        history: [90.1, NaN, 91.2],
        best_lap_time: 85.0,
        last_lap_time: 91.2,
        delta_to_best: -0.4,
    });
    const coords = elements['laptime-canvas'].ctx.ops
        .filter((op) => op.name === 'moveTo' || op.name === 'lineTo')
        .flatMap((op) => op.args);
    assert.ok(coords.length > 0, 'chart must still draw the finite points');
    for (const coord of coords) {
        assert.ok(Number.isFinite(coord), `coordinate must be finite, got ${coord}`);
    }
});

test('laptime graph renders an empty chart without stroking', () => {
    const { elements, handlers } = loadOverlayScript('src/overlays/laptime_graph/static/laptime_graph.js');
    handlers['/laptime_graph:laptime_graph_update']({
        history: [],
        best_lap_time: 85.0,
        last_lap_time: 0.0,
        delta_to_best: 0.0,
    });
    assert.equal(elements['laptime-canvas'].ctx.ops.filter((op) => op.name === 'stroke').length, 0);
    assert.equal(elements['best'].textContent, 'Best: 85.000');
});

test('track map is labelled as a lap-progress ring, not scaled track geometry', () => {
    const html = fs.readFileSync(path.join(repoRoot, 'src/overlays/track_map/track_map.html'), 'utf8');
    assert.match(html, /class="title"[^>]*>Lap Progress</);
    const properties = JSON.parse(
        fs.readFileSync(path.join(repoRoot, 'src/overlays/track_map/properties.json'), 'utf8'),
    );
    assert.match(properties.description, /lap-progress ring/i);
    assert.match(properties.description, /not scaled track geometry/i);
    assert.equal(properties.name, 'track_map');
    assert.equal(properties.display_name, 'Track Map');
});
