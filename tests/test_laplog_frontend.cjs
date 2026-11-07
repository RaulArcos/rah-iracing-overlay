'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
function load(name, theme) {
    const elements = {}, handlers = {}, timers = [], ops = [];
    let ready, now = 1000;
    function element() {
        const el = {children: [], className: '', width: 500, height: 150,
            classList: {toggle() {}}, appendChild(c) {this.children.push(c);},
            getContext: () => new Proxy({}, {get: (_, key) => (...args) => ops.push([key, ...args])})};
        let text = '';
        Object.defineProperty(el, 'textContent', {get: () => text, set(v) {text = String(v); this.children = [];}});
        return el;
    }
    const sandbox = {document: {addEventListener: (_, fn) => ready = fn,
        documentElement: {getAttribute: () => theme}, createElement: element,
        getElementById: id => elements[id] ||= element()},
        io: () => ({on: (key, fn) => handlers[key] = fn}),
        setInterval: fn => timers.push(fn), Date: {now: () => now}, console};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, `../src/overlays/${name}/static/${name}.js`), 'utf8'), sandbox);
    ready();
    return {elements, handlers, ops, stale() {now += 4000; timers.forEach(fn => fn());}};
}
for (const theme of ['original', 'glass']) {
    test(`R3 lap log observed rows, missing values, incident and scale (${theme})`, () => {
        const o = load('laptime_graph', theme);
        o.handlers.laptime_graph_update({history: [92, 91, 93], records: [
            {lap_number: 5, time_s: 92, track_temp_c: 28, incident: null},
            {lap_number: 6, time_s: 91, track_temp_c: 29, incident: false},
            {lap_number: 7, time_s: 93, track_temp_c: null, incident: true}]});
        const rows = o.elements['laplog-rows'].children;
        assert.equal(rows.length, 3);
        assert.equal(rows[0].children[1].textContent, '1:32.000');
        assert.equal(rows[0].children[4].textContent, '--');
        assert.equal(rows[2].children[3].textContent, '--');
        assert.equal(rows[2].children[4].textContent, '×');
        assert.match(rows[1].className, /rah-best/);
        assert.equal(o.elements['log-best'].textContent, '1:31.000');
        const labels = o.ops.filter(x => x[0] === 'fillText').map(x => x[1]);
        assert.ok(labels.some(x => /1:3\d\.\d{3}/.test(x)));
        o.handlers.laptime_graph_update({history: [null, -1, NaN, 92], records: []});
        assert.equal(o.elements['laplog-rows'].children.length, 0);
        o.stale();
        assert.match(o.elements['log-status'].textContent, /Stale/);
        assert.equal(o.elements['log-best'].textContent, '--');
        o.handlers.disconnect();
        assert.match(o.elements['log-status'].textContent, /Disconnected/);
        for (const bad of [null, [], 'x']) {
            o.handlers.laptime_graph_update(bad);
            assert.match(o.elements['log-status'].textContent, /No data/);
        }
    });
    test(`R3 head-to-head recent laps have null holes and safe text (${theme})`, () => {
        const o = load('battle_pace', theme);
        o.handlers.battle_pace_update({context: 'ok', player: {name: 'You'},
            ahead: {name: '<img onerror=alert(1)>', recent_deltas_s: [null, -0.2, 0.3]}});
        const chips = o.elements['bp-ahead-recent'].children;
        assert.deepEqual(chips.map(x => x.textContent), ['--', '-0.200', '+0.300']);
        assert.equal(o.elements['bp-ahead-name'].textContent, '<img onerror=alert(1)>');
        o.stale();
        assert.equal(o.elements['bp-ahead-recent'].children.length, 0);
        for (const name of ['battle_pace', 'laptime_graph']) {
            assert.doesNotMatch(fs.readFileSync(path.join(__dirname, `../src/overlays/${name}/static/${name}.js`), 'utf8'), /innerHTML|insertAdjacentHTML/);
        }
    });
    test(`R3 log source best and guarded missing values (${theme})`, () => {
        const o = load('laptime_graph', theme);
        o.handlers.laptime_graph_update({best_lap_time: 89, records: [
            {lap_number: '<img>', time_s: null, track_temp_c: '<img>', incident: null},
            {lap_number: 9, time_s: 91, track_temp_c: -1, incident: false}]});
        assert.equal(o.elements['log-best'].textContent, '1:29.000');
        assert.equal(o.elements['log-best-temp'].textContent, '--');
        const row = o.elements['laplog-rows'].children[0];
        assert.deepEqual(row.children.map(x => x.textContent), ['--', '--', '--', '--', '--']);
        assert.equal(o.elements['laplog-rows'].children[1].children[3].textContent, '-1.0°C');
        assert.ok(o.ops.filter(x=>x[0]==='arc').every(x=>x.slice(1).every(Number.isFinite)));
        o.handlers.connect_error();
        assert.equal(o.elements['laplog-rows'].children.length, 0);
    });
}
