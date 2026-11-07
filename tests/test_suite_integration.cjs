'use strict';

// Suite integration front-end test (T7, S2-S5).
// Renders the real wire payloads produced by the Python backend
// (`tests/test_suite_integration.py --dump-wire`: one frozen FakeSDK tick, an
// empty SDK and missing sections) with the seven new overlay scripts against
// a stub DOM via node:vm, in both themes. Uses only the Node built-in runner.
// These pin existing T3-T6 behaviour, so they were GREEN on first run.

const test = require('node:test');
const assert = require('node:assert/strict');
const childProcess = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const repoRoot = path.resolve(__dirname, '..');
const OVERLAYS = ['fuel_finish', 'session_strip', 'battle_pace', 'standings',
    'pit_assistant', 'weather', 'broadcast_driver', 'delta'];
const STALE_AFTER_MS = 3000;
const UNRENDERABLE = /\b(NaN|undefined|Infinity|null)\b|\[object/;

function makeElement(id) {
    const classes = new Set();
    let text = '';
    const el = {
        id,
        innerHTML: '',
        children: [],
        classes,
        style: { setProperty() {} },
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

function loadOverlay(name, theme) {
    const elements = {};
    const handlers = {};
    const intervals = [];
    const clock = { now: 1000000 };
    let readyHandler = null;
    const document = {
        documentElement: { getAttribute: () => theme, setAttribute() {} },
        addEventListener(event, handler) {
            if (event === 'DOMContentLoaded') readyHandler = handler;
        },
        getElementById(id) {
            if (!elements[id]) elements[id] = makeElement(id);
            return elements[id];
        },
        createElement: () => makeElement(null),
    };
    const sandbox = {
        document,
        io: () => ({ on(event, handler) { handlers[event] = handler; } }),
        console,
        Date: { now: () => clock.now },
        setInterval: (fn) => { intervals.push(fn); return intervals.length; },
        clearInterval() {},
    };
    vm.createContext(sandbox);
    if (name === 'standings') {
        vm.runInContext(fs.readFileSync(path.join(repoRoot, 'src/common/js/race_metadata.js'), 'utf8'), sandbox);
    }
    const relativePath = `src/overlays/${name}/static/${name}.js`;
    vm.runInContext(fs.readFileSync(path.join(repoRoot, relativePath), 'utf8'), sandbox, { filename: relativePath });
    readyHandler();
    const texts = (el) => [el.textContent, ...el.children.flatMap(texts)];
    return {
        feed: (payload) => handlers[`${name}_update`](payload),
        fire: (event) => handlers[event](),
        advance(ms) { clock.now += ms; intervals.forEach((fn) => fn()); },
        texts: () => Object.values(elements).flatMap(texts),
        snapshot: () => Object.fromEntries(Object.entries(elements).map(([id, el]) => [id, JSON.stringify(
            (function tree(node) { return [node.textContent, [...node.classes].sort(), node.children.map(tree)]; })(el))])),
    };
}

function dumpWire() {
    const run = childProcess.spawnSync('python', ['-B', 'tests/test_suite_integration.py', '--dump-wire'],
        { cwd: repoRoot, encoding: 'utf8' });
    if (run.error || run.status !== 0) return { error: run.error ? String(run.error) : run.stderr.slice(-400) };
    return { wire: JSON.parse(run.stdout) };
}

const { wire, error } = dumpWire();
const options = { skip: error ? `python backend unavailable: ${error}` : false };
// Placeholder dashes plus the sampled-lap counter are the only digits an
// overlay may show when the backend reports nothing.
const digitsOutsidePlaceholders = (texts) => texts.join('|').replace(/\b0 laps\b/g, '').match(/\d/g);

test('backend wire dump covers every new overlay in every scenario', options, () => {
    assert.deepEqual(Object.keys(wire).sort(), ['live', 'missing_sections', 'sdk_empty']);
    for (const scenario of ['live', 'sdk_empty']) {
        assert.equal(Object.keys(wire[scenario]).length, 14, `${scenario}: all 14 overlays receive an event`);
    }
    assert.deepEqual(Object.keys(wire.missing_sections).sort(), [...OVERLAYS].sort());
    assert.equal(wire.live.input_telemetry.gear, 4, 'legacy input event rides the same tick');
});

for (const name of OVERLAYS) {
    for (const scenario of ['live', 'sdk_empty', 'missing_sections']) {
        test(`${name} renders the ${scenario} payload identically in both themes without junk text`, options, () => {
            const original = loadOverlay(name, 'original');
            const glass = loadOverlay(name, 'glass');
            original.feed(wire[scenario][name]);
            glass.feed(wire[scenario][name]);
            assert.deepEqual(glass.snapshot(), original.snapshot());
            for (const text of original.texts()) assert.doesNotMatch(text, UNRENDERABLE);
            const populated = original.texts().filter((text) => /\d/.test(text));
            if (scenario === 'live') {
                assert.ok(populated.length >= 3, `${name} must show real values from the frozen tick`);
            } else {
                // No simulator data means no invented numbers.
                assert.equal(digitsOutsidePlaceholders(original.texts()), null);
            }
        });
    }

    test(`${name} stops showing values when the stream goes stale, disconnects or is nulled`, options, () => {
        for (const ending of ['stale', 'disconnect', 'null']) {
            const overlay = loadOverlay(name, 'original');
            overlay.feed(wire.live[name]);
            assert.ok(digitsOutsidePlaceholders(overlay.texts()), 'live values must be visible first');
            if (ending === 'stale') {
                overlay.advance(STALE_AFTER_MS - 1);
                assert.ok(digitsOutsidePlaceholders(overlay.texts()), 'still fresh before the threshold');
                overlay.advance(2);
                assert.ok(overlay.texts().includes('Stale: no data'), name);
            } else if (ending === 'disconnect') {
                overlay.fire('disconnect');
                assert.ok(overlay.texts().includes('Disconnected'), name);
            } else {
                overlay.feed(wire.missing_sections[name]);
                assert.ok(overlay.texts().includes('No data'), name);
            }
            assert.equal(digitsOutsidePlaceholders(overlay.texts()), null, `${name} after ${ending}`);
        }
    });
}
