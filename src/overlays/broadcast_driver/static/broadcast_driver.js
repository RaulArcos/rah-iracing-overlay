document.addEventListener("DOMContentLoaded", function() {
    const socket = io('/broadcast_driver', {
        reconnection: true,
        reconnectionAttempts: Infinity,
        reconnectionDelay: 1000,
        reconnectionDelayMax: 5000,
        timeout: 20000
    });

    const UNAVAILABLE = '—';
    const STALE_AFTER_MS = 3000;

    const numberEl = document.getElementById('bd-number');
    const nameEl = document.getElementById('bd-name');
    const classEl = document.getElementById('bd-class');
    const positionEl = document.getElementById('bd-position');
    const classPositionEl = document.getElementById('bd-class-position');
    const lapsEl = document.getElementById('bd-laps');
    const lastEl = document.getElementById('bd-last');
    const bestEl = document.getElementById('bd-best');
    const pitEl = document.getElementById('bd-pit');
    const sessionEl = document.getElementById('bd-session');
    const cameraEl = document.getElementById('bd-camera');
    const statusEl = document.getElementById('bd-status');
    const valueEls = [numberEl, nameEl, classEl, positionEl, classPositionEl, lapsEl, lastEl, bestEl,
        pitEl, sessionEl, cameraEl];

    let lastUpdate = null;

    function text(value) {
        return typeof value === 'string' && value.trim().length ? value.trim() : null;
    }

    // Ranks and counters are whole numbers; anything else is unavailable.
    function whole(value, minimum) {
        return typeof value === 'number' && Number.isInteger(value) && value >= minimum ? value : null;
    }

    function lapTime(seconds) {
        if (typeof seconds !== 'number' || !isFinite(seconds) || seconds <= 0) {
            return UNAVAILABLE;
        }
        const ms = Math.round(seconds * 1000);
        const minutes = Math.floor(ms / 60000);
        const rest = ((ms % 60000) / 1000).toFixed(3);
        return minutes + ':' + (rest.length < 6 ? '0' : '') + rest;
    }

    function setLevel(el, level) {
        el.classList.toggle('rah-status--ok', level === 'ok');
        el.classList.toggle('rah-status--warn', level === 'warn');
        el.classList.toggle('rah-status--bad', level === 'bad');
    }

    function setStatus(label, level) {
        statusEl.textContent = label;
        setLevel(statusEl, level);
    }

    function clear(label, level) {
        lastUpdate = null;
        valueEls.forEach(function(el) {
            el.textContent = UNAVAILABLE;
            setLevel(el, null);
        });
        setStatus(label, level);
    }

    function show(el, value, format) {
        el.textContent = value === null ? UNAVAILABLE : format(value);
    }

    function render(data) {
        const identity = data.identity_available === true;
        const number = identity ? text(data.car_number) : null;
        const name = identity ? text(data.name) : null;
        show(numberEl, number, function(v) { return '#' + v; });
        // Never a made-up "Car N": a missing identity says so.
        nameEl.textContent = name !== null ? name : (identity ? UNAVAILABLE : 'Identity unavailable');
        show(classEl, identity ? text(data.class_name) : null, String);
        show(positionEl, whole(data.position, 1), function(v) { return 'P' + v; });
        show(classPositionEl, whole(data.class_position, 1), function(v) { return 'C' + v; });
        show(lapsEl, whole(data.laps_completed, 0), String);
        lastEl.textContent = lapTime(data.last_lap_s);
        bestEl.textContent = lapTime(data.best_lap_s);
        if (typeof data.on_pit_road === 'boolean') {
            pitEl.textContent = data.on_pit_road ? 'IN PIT' : 'ON TRACK';
            setLevel(pitEl, data.on_pit_road ? 'warn' : null);
        } else {
            pitEl.textContent = UNAVAILABLE;
            setLevel(pitEl, null);
        }
        show(sessionEl, text(data.session_type), String);
        show(cameraEl, whole(data.camera_car_idx, 0), String);
        setStatus('Live', 'ok');
    }

    socket.on('connect', function() {
        clear('Waiting for data', 'warn');
    });

    socket.on('disconnect', function() {
        clear('Disconnected', 'bad');
    });

    socket.on('connect_error', function() {
        clear('Disconnected', 'bad');
    });

    socket.on('broadcast_driver_update', function(data) {
        if (!data || typeof data !== 'object' || Array.isArray(data)) {
            clear('No data', 'warn');
            return;
        }
        if (data.available !== true) {
            // The whole previous card goes away with the camera target.
            clear(data.reason === 'camera_target_excluded' ? 'Camera on pace car/spectator'
                : 'No camera target', 'warn');
            lastUpdate = Date.now();
            return;
        }
        lastUpdate = Date.now();
        render(data);
    });

    setInterval(function() {
        if (lastUpdate !== null && Date.now() - lastUpdate > STALE_AFTER_MS) {
            clear('Stale: no data', 'warn');
        }
    }, 1000);
});
