const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const root = require('node:path').join(__dirname, '..');
const load = file => fs.readFileSync(require('node:path').join(root, file), 'utf8');

test('scenario is deterministic, complete and coherent across widgets', () => {
    const context = vm.createContext({});
    vm.runInContext(load('src/common/js/demo_race.js'), context);
    vm.runInContext(load('src/common/js/demo_scenario.js'), context);
    const frame = context.RAHDemoScenario.frame;
    const a = frame(320), b = frame(320);
    assert.equal(JSON.stringify(a), JSON.stringify(b));
    assert.equal(Object.keys(a).length, 14);
    assert.equal(a.laptime_graph.records.length, 10);
    assert.equal(a.standings.classes.length, 3);
    assert.equal(a.relative.player.name, a.broadcast_driver.name);
    assert.equal(a.battle_pace.player.last_lap_s, a.broadcast_driver.last_lap_s);
    assert.equal(a.session_strip.position, a.relative.player_position);
    assert.notEqual(JSON.stringify(a), JSON.stringify(frame(350)));
    assert.equal(a.weather.wind_speed_kmh, a.weather.wind_speed_ms * 3.6);
    for (const payload of Object.values(a)) assert.equal(payload.simulated, true);
});

test('menu selects PNG before legacy GIF and pins only demo link theme', () => {
    const context = vm.createContext({window: {}});
    vm.runInContext(load('src/interface/static/previews.js'), context);
    const api = context.window.RAHMenuPreviews;
    const overlay = {folder_name:'radar', preview_images:{glass:'/glass.png'}, preview_gif:'/old.gif'};
    assert.equal(api.imageUrl(overlay, 'glass'), '/glass.png');
    assert.equal(api.imageUrl(overlay, 'original'), '/old.gif');
    assert.equal(api.demoUrl(overlay, 'glass'), '/overlay/radar?demo=1&theme=glass');
    assert.equal(api.imageUrl({}, 'glass'), null);
});

test('new feature code has no unsafe HTML, storage writes or transport constructors', () => {
    for (const file of ['src/common/js/demo_race.js', 'src/common/js/demo_scenario.js',
        'src/common/js/demo_adapter.js', 'src/interface/static/previews.js']) {
        const source = load(file);
        assert.doesNotMatch(source, /innerHTML|Math\.random|\.emit\(|new WebSocket|XMLHttpRequest|localStorage\.setItem/);
    }
});

test('adapter replaces io before consumers, supports connect, pause, step and heartbeat without transport', () => {
    const handlers = {}, timers = [];
    const element = () => ({style:{setProperty() {}}, append() {}, appendChild() {},
        setAttribute() {}, addEventListener() {}, getBoundingClientRect: () => ({height:64})});
    const document = {head:element(), body:element(), documentElement:element(),
        createElement:element, addEventListener: (name, callback) => { handlers[name] = callback; }};
    const window = {location:{search:'?demo=1'}, setInterval:callback => timers.push(callback),
        io: () => { throw Error('real io invoked'); }};
    const context = vm.createContext({window, document, URLSearchParams,
        ResizeObserver: class {observe() {}}});
    vm.runInContext(load('src/common/js/demo_race.js'), context);
    vm.runInContext(load('src/common/js/demo_scenario.js'), context);
    window.RAHDemoScenario = context.RAHDemoScenario;
    vm.runInContext(load('src/common/js/demo_adapter.js'), context);
    let connects = 0, updates = 0, beats = 0, payload;
    const socket = window.io('/input_telemetry');
    assert.equal(socket.on('connect', () => connects++), socket);
    socket.on('telemetry_update', data => { updates++; payload = data; });
    const weather = window.io('/weather').on('heartbeat', () => beats++);
    assert.equal(weather.connect(), weather);
    handlers.DOMContentLoaded();
    assert.equal(connects, 1);
    // 1 connect frame + 300 steps + 301 seeded ~30 Hz input-history samples.
    assert.equal(updates, 602);
    assert.equal(payload.simulated, true);
    assert.equal(window.RAHDemo.ready, true);
    assert.equal(window.RAHDemo.tick, 300);
    assert.equal(timers.length, 1);
    timers[0]();
    assert.equal(window.RAHDemo.tick, 301);
    window.RAHDemo.pause();
    const frozen = updates, beatCount = beats;
    timers[0]();
    assert.equal(window.RAHDemo.tick, 301);
    assert.equal(updates, frozen);
    assert.equal(beats, beatCount + 1);
    window.RAHDemo.step(4);
    assert.equal(window.RAHDemo.tick, 305);
    assert.throws(() => window.RAHDemo.step(-1), /Invalid/);
    window.RAHDemo.seek();
    assert.equal(window.RAHDemo.tick, 300);
    assert.equal(window.RAHDemo.paused, true);
    window.RAHDemo.resume();
    timers[0]();
    assert.equal(window.RAHDemo.tick, 301);
});

test('adapter guard leaves existing io untouched for every non-exact query', () => {
    for (const search of ['', '?demo=0', '?demo=true', '?demo=01', '?demo=1&demo=0']) {
        const io = () => {};
        const window = {location:{search}, io};
        vm.runInNewContext(load('src/common/js/demo_adapter.js'), {window, URLSearchParams});
        assert.equal(window.io, io);
        assert.equal(window.RAHDemo, undefined);
    }
});
