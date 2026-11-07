'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function load(name) {
    const elements = {}, handlers = {}, timers = [];
    let ready, now = 10000;
    function element() {
        const classes = new Set();
        let text = '';
        return { get textContent() { return text; }, set textContent(value) { text = String(value); this.children = []; }, children: [], classes, style: { setProperty(k, v) { this[k] = v; } },
            appendChild(el) { this.children.push(el); },
            replaceChildren(...els) { this.children = els; },
            classList: { toggle(k, on) { if (on) classes.add(k); else classes.delete(k); } } };
    }
    const sandbox = { console, Date: { now: () => now }, setInterval: fn => timers.push(fn),
        document: { addEventListener: (evt, fn) => { ready = fn; }, createElement: element,
            getElementById: id => elements[id] ||= element() },
        io: () => ({ on: (evt, fn) => { handlers[evt] = fn; } }) };
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, `../src/overlays/${name}/static/${name}.js`), 'utf8'), sandbox);
    ready();
    return { elements, handlers, update: data => handlers[`${name}_update`](data),
        advance(ms) { now += ms; timers.forEach(fn => fn()); } };
}
const active = (p, id) => p.elements[id].classes.has('active');

for (const name of ['radar', 'blindspot']) {
    const ids = name === 'radar' ? ['left-alert', 'right-alert'] : ['left-zone', 'right-zone'];
    const status = name === 'radar' ? 'radar-status' : 'status-msg';
    test(`${name}: strict boolean flags, partial unknown, strongest both warning`, () => {
        const p = load(name);
        assert.match(p.elements[status].textContent, /unavailable/i);
        p.update({ left_alert: 'true', right_alert: 1, message: 'CLEAR' });
        assert.equal(active(p, ids[0]), false);
        assert.equal(active(p, ids[1]), false);
        assert.match(p.elements[status].textContent, /unavailable/i);
        p.update({ left_alert: true });
        assert.equal(active(p, ids[0]), true);
        assert.match(p.elements[status].textContent, /unavailable/i);
        p.update({ left_alert: true, right_alert: true, both_alert: false });
        assert.equal(active(p, ids[1]), true);
        assert.match(p.elements[status].textContent, /BOTH/);
        assert.ok(p.elements['proximity-panel'].classes.has('both-active'));
        p.update({ left_alert: false, right_alert: false, message: '<img onerror=bad>' });
        assert.match(p.elements[status].textContent, /No side alerts/);
    });
    test(`${name}: null, disconnect, connect_error and silence discard warnings`, () => {
        const p = load(name);
        for (const clear of [() => p.update(null), () => p.handlers.disconnect(),
            () => p.handlers.connect_error(), () => p.advance(3001)]) {
            p.update({ left_alert: true, right_alert: true, nearby: [{ distance_pct: .001, car_idx: 1 }], track_length_m: 5000 });
            clear();
            assert.equal(active(p, ids[0]), false);
            assert.equal(active(p, ids[1]), false);
            assert.match(p.elements[status].textContent, /unavailable|stale|disconnected/i);
            if (name === 'radar') assert.equal(p.elements['ahead-distance'].textContent, '-- m');
        }
        p.update({ left_alert: true, right_alert: false });
        p.advance(3000);
        assert.equal(active(p, ids[0]), true);
    });
}

test('radar: nearest signed distances, bounded bars and literal metadata', () => {
    const p = load('radar');
    p.update({ left_alert: false, right_alert: false, track_length_m: 5000, nearby: [null, {},
        { distance_pct: NaN }, { distance_pct: '0.001' },
        { car_idx: 8, car_number: '<img>', distance_pct: .02, relation: 'behind' },
        { car_idx: 4, distance_pct: .001, relation: 'behind' },
        { car_idx: 3, distance_pct: -.002, relation: 'ahead' }] });
    assert.equal(p.elements['ahead-distance'].textContent, '~5 m');
    assert.equal(p.elements['behind-distance'].textContent, '~10 m');
    assert.equal(p.elements['ahead-fill'].style.height, '95%');
    assert.equal(p.elements['behind-fill'].style.height, '90%');
    assert.match(p.elements['nearby-list'].children.map(el => el.textContent).join(' '), /Car 8.*AHEAD ~100m/);
    assert.ok(p.elements['traffic-markers'].children.some(el => el.textContent === '#<img>'));
    p.update({ track_length_m: 5000, nearby: [{ distance_pct: 0, relation: 'behind', car_idx: 1 }] });
    assert.equal(p.elements['ahead-distance'].textContent, '-- m');
    assert.equal(p.elements['behind-distance'].textContent, '-- m');
    assert.match(p.elements['nearby-list'].children[0].textContent, /COINCIDENT ~0m/);
    assert.equal(p.elements['distance-source'].textContent, 'COINCIDENT ~0 m · lap-progress estimate');
});

test('radar: missing or invalid length/data cannot invent meters or a safe state', () => {
    const p = load('radar');
    for (const length of [undefined, null, 0, -1, NaN, Infinity, '5000']) {
        p.update({ track_length_m: length, nearby: [{ distance_pct: .02, car_idx: 2 }] });
        assert.equal(p.elements['ahead-distance'].textContent, '-- m');
        assert.equal(p.elements['ahead-fill'].style.height, '0%');
        assert.match(p.elements['ahead-meta'].textContent, /2.00% lap/);
        assert.match(p.elements['radar-status'].textContent, /unavailable/);
    }
    for (const nearby of [null, {}, [null, { distance_pct: Infinity }]]) {
        p.update({ left_alert: false, right_alert: false, track_length_m: 5000, nearby });
        assert.equal(p.elements['ahead-distance'].textContent, '-- m');
        assert.equal(p.elements['behind-distance'].textContent, '-- m');
        assert.doesNotMatch(p.elements['radar-status'].textContent, /safe|clear/i);
    }
});

test('radar: actual car glyphs move on one signed axis, own excluded, side alerts never identify rivals', () => {
    const p = load('radar');
    const payload = {player_car_idx: 0, track_length_m: 5000, left_alert: true, right_alert: true,
        nearby: [0, 1, 2, 3, 4].map((car_idx, i) => ({car_idx, distance_pct: [0, .004, .016, -.004, -.016][i]}))};
    p.update(payload);
    const markers = () => p.elements['traffic-markers'].children;
    assert.equal(markers().length, 4);
    const markerFor = idx => markers().find(marker => marker.textContent === 'IDX ' + idx);
    assert.deepEqual([1, 2, 3, 4].map(idx => parseFloat(markerFor(idx).style.top)), [42, 18, 58, 82]);
    assert.ok(markers().every(m => m.className.includes('traffic-car')));
    assert.ok(markers().every(m => !/left|right/i.test(m.textContent)));
    payload.nearby[1].distance_pct = .008;
    payload.nearby[3].distance_pct = -.008;
    p.update(payload);
    assert.equal(parseFloat(markerFor(1).style.top), 34);
    assert.equal(parseFloat(markerFor(3).style.top), 66);
    for (const clear of [() => p.update(null), () => p.handlers.disconnect(),
        () => p.handlers.connect_error(), () => p.advance(3001)]) {
        p.update(payload); clear(); assert.equal(markers().length, 0);
    }
});

test('radar: metric unavailability, invalid IDs, out-of-range and overlap are explicit', () => {
    const p = load('radar');
    const nearby = [{car_idx: 1, distance_pct: 0}, {car_idx: 2, distance_pct: 0},
        {car_idx: 3, distance_pct: .03}, {car_idx: -1, distance_pct: .001},
        {car_idx: '<img>', distance_pct: .002}, {car_idx: 4, distance_pct: 0, is_player: true}];
    p.update({track_length_m: 5000, nearby});
    const markers = p.elements['traffic-markers'].children;
    assert.equal(markers.length, 1);
    assert.match(markers[0].textContent, /2 cars.*IDX 1.*IDX 2/);
    assert.equal(markers[0].style.top, '50%');
    assert.match(p.elements['traffic-range'].textContent, /1 outside/);
    p.update({nearby});
    assert.equal(p.elements['traffic-markers'].children.length, 0);
    assert.match(p.elements['traffic-range'].textContent, /length unavailable/);
    p.update({track_length_m: 5000, nearby: [{car_idx: 1, distance_pct: .01, name: '<img onerror=bad>'}]});
    assert.equal(p.elements['traffic-markers'].children.length, 1);
    assert.match(p.elements['traffic-markers'].children[0].textContent, /IDX 1/);
});

test('radar: clusters preserve ahead, behind and coincident positions independently of input order', () => {
    const p = load('radar');
    const update = cars => p.update({player_car_idx: 0, track_length_m: 5000,
        nearby: cars.map(([car_idx, meters]) => ({car_idx, distance_pct: meters / 5000}))});
    const snapshot = () => p.elements['traffic-markers'].children.map(marker => ({
        text: marker.textContent, top: marker.style.top, title: marker.title}));
    update([[1, 10], [2, -10]]);
    const before = snapshot();
    assert.equal(before.length, 2);
    assert.equal(before.find(marker => marker.text === 'IDX 1').top, '46%');
    assert.equal(before.find(marker => marker.text === 'IDX 2').top, '54%');
    update([[2, -10], [1, 10]]);
    assert.deepEqual(snapshot(), before);
    update([[1, 10], [2, -20]]);
    assert.equal(snapshot().find(marker => marker.text === 'IDX 2').top, '58%');
    update([[1, 60], [2, 25], [3, -10]]);
    const chain = snapshot();
    update([[2, 25], [1, 60], [3, -10]]);
    assert.deepEqual(snapshot(), chain);
    assert.equal(chain.length, 2);
    assert.equal(chain.find(marker => marker.text === 'IDX 3').top, '54%');
    update([[1, 10], [2, -10], [3, 0]]);
    assert.equal(snapshot().length, 3);
    assert.equal(snapshot().find(marker => marker.text === 'IDX 3').top, '50%');
});
