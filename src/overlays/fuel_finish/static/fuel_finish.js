document.addEventListener("DOMContentLoaded", function() {
    const socket = io('/fuel_finish', {
        reconnection: true,
        reconnectionAttempts: Infinity,
        reconnectionDelay: 1000,
        reconnectionDelayMax: 5000,
        timeout: 20000
    });

    const UNAVAILABLE = '--';
    const STALE_AFTER_MS = 3000;
    const BASIS_LABELS = {
        laps_remaining: 'Finish: laps remaining',
        timed_conservative_estimate: 'Finish: timed estimate (conservative)'
    };

    const levelEl = document.getElementById('fuel-level');
    const pctEl = document.getElementById('fuel-pct');
    const burnEl = document.getElementById('fuel-burn');
    const lapsEl = document.getElementById('fuel-laps');
    const finishLapsEl = document.getElementById('fuel-finish-laps');
    const neededEl = document.getElementById('fuel-needed');
    const addEl = document.getElementById('fuel-add');
    const samplesEl = document.getElementById('fuel-samples');
    const basisEl = document.getElementById('fuel-basis');
    const statusEl = document.getElementById('fuel-status');

    let lastUpdate = null;

    function isNumber(value) {
        return typeof value === 'number' && isFinite(value);
    }

    function fmt(value, digits) {
        return isNumber(value) ? value.toFixed(digits) : UNAVAILABLE;
    }

    function fmtLaps(value) {
        if (!isNumber(value)) {
            return UNAVAILABLE;
        }
        return Number.isInteger(value) ? String(value) : value.toFixed(1);
    }

    function setStatus(text, level) {
        statusEl.textContent = text;
        statusEl.classList.toggle('rah-status--ok', level === 'ok');
        statusEl.classList.toggle('rah-status--warn', level === 'warn');
        statusEl.classList.toggle('rah-status--bad', level === 'bad');
    }

    function clear(text, level) {
        lastUpdate = null;
        [levelEl, pctEl, burnEl, lapsEl, finishLapsEl, neededEl, addEl, basisEl].forEach(function(el) {
            el.textContent = UNAVAILABLE;
        });
        samplesEl.textContent = '0 laps';
        setStatus(text, level);
    }

    function render(data) {
        levelEl.textContent = fmt(data.fuel_level_l, 1);
        pctEl.textContent = isNumber(data.fuel_level_pct) ? data.fuel_level_pct.toFixed(0) + '%' : UNAVAILABLE;
        burnEl.textContent = fmt(data.avg_burn_l_per_lap, 2);
        lapsEl.textContent = fmt(data.laps_of_fuel, 1);
        finishLapsEl.textContent = fmtLaps(data.finish_laps_remaining);
        neededEl.textContent = fmt(data.finish_fuel_needed_l, 1);
        addEl.textContent = fmt(data.finish_fuel_to_add_l, 1);
        basisEl.textContent = BASIS_LABELS[data.finish_basis] || UNAVAILABLE;

        const count = isNumber(data.burn_sample_count) ? Math.max(0, Math.floor(data.burn_sample_count)) : 0;
        samplesEl.textContent = count + (count === 1 ? ' lap' : ' laps');

        if (!isNumber(data.fuel_level_l)) {
            setStatus('No fuel data', 'bad');
        } else if (count === 0) {
            setStatus('Learning burn', 'warn');
        } else {
            setStatus('Estimate', 'ok');
        }
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

    socket.on('fuel_finish_update', function(data) {
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
