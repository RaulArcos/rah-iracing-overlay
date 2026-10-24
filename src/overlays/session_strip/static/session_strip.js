document.addEventListener("DOMContentLoaded", function() {
    const socket = io('/session_strip', {
        reconnection: true,
        reconnectionAttempts: Infinity,
        reconnectionDelay: 1000,
        reconnectionDelayMax: 5000,
        timeout: 20000
    });

    const UNAVAILABLE = '--';
    const STALE_AFTER_MS = 3000;
    const LIMIT_LABELS = {
        laps: 'LAPS',
        time: 'TIME',
        laps_and_time: 'LAPS + TIME',
        unlimited: 'UNLIMITED'
    };
    // Highest priority first; names are the installed irsdk.Flags members.
    const FLAG_PRIORITY = [
        ['red', 'bad'], ['black', 'bad'], ['disqualify', 'bad'], ['repair', 'bad'],
        ['checkered', 'ok'],
        ['yellow_waving', 'warn'], ['yellow', 'warn'], ['caution_waving', 'warn'],
        ['caution', 'warn'], ['debris', 'warn'],
        ['blue', null], ['white', null],
        ['green', 'ok'], ['green_held', 'ok'], ['one_lap_to_green', 'warn'],
        ['five_to_go', null], ['ten_to_go', null]
    ];

    const typeEl = document.getElementById('strip-type');
    const limitEl = document.getElementById('strip-limit');
    const stateEl = document.getElementById('strip-state');
    const flagEl = document.getElementById('strip-flag');
    const lapsEl = document.getElementById('strip-laps');
    const timeEl = document.getElementById('strip-time');
    const lapEl = document.getElementById('strip-lap');
    const posEl = document.getElementById('strip-pos');
    const classPosEl = document.getElementById('strip-class-pos');
    const statusEl = document.getElementById('strip-status');

    let lastUpdate = null;

    function isNumber(value) {
        return typeof value === 'number' && isFinite(value);
    }

    function pad(value) {
        return value < 10 ? '0' + value : String(value);
    }

    function formatTime(seconds) {
        if (!isNumber(seconds) || seconds < 0) {
            return UNAVAILABLE;
        }
        const total = Math.floor(seconds);
        const hours = Math.floor(total / 3600);
        const minutes = Math.floor((total % 3600) / 60);
        const secs = total % 60;
        return hours > 0 ? hours + ':' + pad(minutes) + ':' + pad(secs) : minutes + ':' + pad(secs);
    }

    function label(value) {
        return typeof value === 'string' && value.length ? value.replace(/_/g, ' ').toUpperCase() : UNAVAILABLE;
    }

    function setLevel(el, level) {
        el.classList.toggle('rah-status--ok', level === 'ok');
        el.classList.toggle('rah-status--warn', level === 'warn');
        el.classList.toggle('rah-status--bad', level === 'bad');
    }

    function renderFlag(flags) {
        if (!Array.isArray(flags)) {
            flagEl.textContent = UNAVAILABLE;
            setLevel(flagEl, null);
            return;
        }
        for (let i = 0; i < FLAG_PRIORITY.length; i++) {
            if (flags.indexOf(FLAG_PRIORITY[i][0]) !== -1) {
                flagEl.textContent = label(FLAG_PRIORITY[i][0]);
                setLevel(flagEl, FLAG_PRIORITY[i][1]);
                return;
            }
        }
        flagEl.textContent = flags.length ? label(flags[0]) : 'NONE';
        setLevel(flagEl, null);
    }

    function setStatus(text, level) {
        statusEl.textContent = text;
        setLevel(statusEl, level);
    }

    function clear(text, level) {
        lastUpdate = null;
        [typeEl, limitEl, stateEl, flagEl, lapsEl, timeEl, lapEl, posEl, classPosEl].forEach(function(el) {
            el.textContent = UNAVAILABLE;
        });
        setLevel(flagEl, null);
        setStatus(text, level);
    }

    function render(data) {
        typeEl.textContent = typeof data.session_type === 'string' && data.session_type.length
            ? data.session_type : UNAVAILABLE;
        limitEl.textContent = LIMIT_LABELS[data.limit] || UNAVAILABLE;
        stateEl.textContent = label(data.state);
        renderFlag(data.flags);
        lapsEl.textContent = isNumber(data.laps_remaining) ? String(data.laps_remaining) : UNAVAILABLE;
        timeEl.textContent = formatTime(data.time_remaining_s);
        lapEl.textContent = isNumber(data.lap) ? String(data.lap) : UNAVAILABLE;
        posEl.textContent = isNumber(data.position) ? 'P' + data.position : UNAVAILABLE;
        classPosEl.textContent = isNumber(data.class_position) ? 'C' + data.class_position : UNAVAILABLE;
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

    socket.on('session_strip_update', function(data) {
        if (!data || typeof data !== 'object' || Array.isArray(data)) {
            clear('No data', 'warn');
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
