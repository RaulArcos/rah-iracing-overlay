/* Exact opt-in only. Replaces io before any widget's DOMContentLoaded handler. */
(function (global) {
    'use strict';
    const params = new URLSearchParams(global.location.search);
    if (params.getAll('demo').length !== 1 || params.get('demo') !== '1') return;
    const sockets = [];
    let tick = 0, paused = false, ready = false;
    function dispatch(refreshOnly = false) {
        const data = global.RAHDemoScenario.frame(tick);
        sockets.forEach(socket => {
            const name = socket.namespace.replace(/^\//, '');
            // Input history must freeze too. These two widgets have no stale
            // timeout; the others receive an unchanged frame to keep labels up.
            if (refreshOnly && ['input_telemetry', 'track_map'].includes(name)) return;
            const event = name === 'input_telemetry' ? 'telemetry_update' : name + '_update';
            (socket.handlers[event] || []).forEach(handler => handler(data[name]));
            (socket.handlers.heartbeat || []).forEach(handler => handler({simulated: true}));
        });
    }
    global.io = function (namespace) {
        const socket = {namespace, handlers: {}, connected: true,
            on(event, handler) {
                (this.handlers[event] ||= []).push(handler);
                return this;
            },
            connect() {
                (this.handlers.connect || []).forEach(handler => handler());
                return this;
            }};
        sockets.push(socket);
        return socket;
    };
    const api = {
        get tick() { return tick; },
        get paused() { return paused; },
        get ready() { return ready; },
        pause() { paused = true; updateButton(); },
        resume() { paused = false; updateButton(); },
        step(count = 1) {
            if (!Number.isInteger(count) || count < 0 || count > 2000) throw new RangeError('Invalid step count');
            for (let i = 0; i < count; i++) { tick++; dispatch(); }
        },
        seek(frame = 300) {
            if (!Number.isInteger(frame) || frame < 0 || frame > 1440) throw new RangeError('Invalid frame');
            tick = 0;
            dispatch();
            this.step(frame);
            seedInputHistory();
            this.pause();
        }
    };
    // Fill the input graph with the last 10 s at the live ~30 Hz resolution
    // (instead of 75 s of 4 Hz steps squeezed into the same width).
    function seedInputHistory() {
        const data = n => global.RAHDemoScenario.frame(n).input_telemetry;
        sockets.filter(socket => socket.namespace === '/input_telemetry').forEach(socket => {
            for (let k = 0; k <= 300; k++) {
                const sample = data(tick - 40 + k * 40 / 300);
                (socket.handlers.telemetry_update || []).forEach(handler => handler(sample));
            }
        });
    }
    global.RAHDemo = api;
    let button;
    function updateButton() { if (button) button.textContent = paused ? 'Resume' : 'Pause'; }
    document.addEventListener('DOMContentLoaded', () => {
        const style = document.createElement('style');
        style.textContent = `html { overflow: auto !important; }
            html, body { transform: none !important; will-change: auto !important; }
            body { margin-top: var(--rah-demo-offset, 76px) !important; overflow: visible !important; }
            #rah-demo-toolbar { position: fixed; top: 0; left: 0; right: 0; z-index: 99999;
                box-sizing: border-box; min-height: 64px; padding: 10px 12px; background: #20232a;
                color: #fff; font: 13px/1.5 'Segoe UI', sans-serif; display: flex;
                gap: 12px; align-items: center; border-bottom: 2px solid #f2ca52; }
            #rah-demo-toolbar button { padding: 6px 12px; cursor: pointer; }
            #rah-demo-toolbar span { flex: 1; }`;
        document.head.appendChild(style);
        const toolbar = document.createElement('aside');
        toolbar.id = 'rah-demo-toolbar';
        toolbar.setAttribute('aria-label', 'Simulated telemetry controls');
        const caption = document.createElement('span');
        caption.textContent = 'Simulated telemetry / not iRacing — fictional race, ratings and timing; not official data';
        button = document.createElement('button');
        button.type = 'button';
        button.addEventListener('click', () => paused ? api.resume() : api.pause());
        updateButton();
        toolbar.append(caption, button);
        document.body.appendChild(toolbar);
        const reserveToolbar = () => document.documentElement.style.setProperty(
            '--rah-demo-offset', Math.ceil(toolbar.getBoundingClientRect().height + 12) + 'px');
        reserveToolbar();
        new ResizeObserver(reserveToolbar).observe(toolbar);
        sockets.forEach(socket => socket.connect());
        dispatch();
        // Populate history immediately instead of waiting 75 seconds for a
        // full input graph. Subsequent frames continue from this race snapshot.
        api.step(300);
        seedInputHistory();
        ready = true;
        const clock = () => (global.performance && global.performance.now ? global.performance.now() : Date.now());
        let lastTick = clock(), lastFrame = 0;
        global.setInterval(() => {
            // Keep stale guards fed while paused, without advancing the scenario.
            if (!paused) { tick++; lastTick = clock(); }
            dispatch(paused);
        }, 250);
        // Smooth in-between frames (~30 fps) for the continuously moving widgets
        // only; tables stay on the 4 Hz scenario tick. rAF stops when hidden.
        const fluid = ['input_telemetry', 'track_map', 'relative', 'radar', 'delta'];
        function smooth(now) {
            global.requestAnimationFrame(smooth);
            if (paused || now - lastFrame < 32) return;
            lastFrame = now;
            const fraction = Math.min(.999, (now - lastTick) / 250);
            const data = global.RAHDemoScenario.frame(tick + fraction);
            sockets.forEach(socket => {
                const name = socket.namespace.replace(/^\//, '');
                if (!fluid.includes(name)) return;
                const event = name === 'input_telemetry' ? 'telemetry_update' : name + '_update';
                (socket.handlers[event] || []).forEach(handler => handler(data[name]));
            });
        }
        if (typeof global.requestAnimationFrame === 'function') global.requestAnimationFrame(smooth);
    });
}(window));
