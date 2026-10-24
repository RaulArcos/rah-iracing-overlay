document.addEventListener("DOMContentLoaded", function() {
    const socket = io('/pit_assistant', {
        reconnection: true,
        reconnectionAttempts: Infinity,
        reconnectionDelay: 1000,
        reconnectionDelayMax: 5000,
        timeout: 20000
    });

    const UNAVAILABLE = '—';
    const STALE_AFTER_MS = 3000;

    const speedEl = document.getElementById('pit-speed');
    const limitEl = document.getElementById('pit-limit');
    const marginEl = document.getElementById('pit-margin');
    const limitStateEl = document.getElementById('pit-limit-state');
    const roadEl = document.getElementById('pit-road');
    const stallEl = document.getElementById('pit-stall');
    const openEl = document.getElementById('pit-open');
    const serviceEl = document.getElementById('pit-service');
    const repairEl = document.getElementById('pit-repair');
    const optRepairEl = document.getElementById('pit-opt-repair');
    const towEl = document.getElementById('pit-tow');
    const flagsEl = document.getElementById('pit-flags');
    const svStatusEl = document.getElementById('pit-svstatus');
    const fuelEl = document.getElementById('pit-fuel');
    const statusEl = document.getElementById('pit-status');
    const valueEls = [speedEl, limitEl, marginEl, limitStateEl, roadEl, stallEl, openEl, serviceEl,
        repairEl, optRepairEl, towEl, flagsEl, svStatusEl, fuelEl];

    let lastUpdate = null;

    function isNumber(value) {
        return typeof value === 'number' && isFinite(value);
    }

    function fixed(value) {
        return isNumber(value) ? value.toFixed(1) : UNAVAILABLE;
    }

    function label(value) {
        return typeof value === 'string' && value.length ? value.replace(/_/g, ' ').toUpperCase() : null;
    }

    function setLevel(el, level) {
        el.classList.toggle('rah-status--ok', level === 'ok');
        el.classList.toggle('rah-status--warn', level === 'warn');
        el.classList.toggle('rah-status--bad', level === 'bad');
    }

    // A chip always carries its meaning in text; the colour is only a hint.
    function setFlag(el, value, onText, offText, onLevel, offLevel) {
        if (typeof value !== 'boolean') {
            el.textContent = UNAVAILABLE;
            setLevel(el, null);
            return;
        }
        el.textContent = value ? onText : offText;
        setLevel(el, value ? onLevel : offLevel);
    }

    function renderLimitState(state) {
        if (state === 'over_limit') {
            limitStateEl.textContent = 'OVER LIMIT';
            setLevel(limitStateEl, 'bad');
        } else if (state === 'within_limit') {
            limitStateEl.textContent = 'WITHIN LIMIT';
            setLevel(limitStateEl, 'ok');
        } else {
            limitStateEl.textContent = UNAVAILABLE;
            setLevel(limitStateEl, null);
        }
    }

    function renderMargin(margin) {
        marginEl.textContent = isNumber(margin) ? (margin > 0 ? '+' : '') + margin.toFixed(1) : UNAVAILABLE;
    }

    function renderFlags(data) {
        if (!Array.isArray(data.service_flags)) {
            flagsEl.textContent = UNAVAILABLE;
        } else if (data.service_flags.length) {
            flagsEl.textContent = data.service_flags.map(label).join(', ');
        } else {
            // Bits the installed SDK enum does not name stay visible as raw.
            flagsEl.textContent = isNumber(data.service_flags_raw) && data.service_flags_raw !== 0
                ? 'RAW ' + data.service_flags_raw : 'NONE';
        }
    }

    function renderStatus(data) {
        const name = label(data.service_status);
        if (name) {
            svStatusEl.textContent = name;
        } else {
            svStatusEl.textContent = isNumber(data.service_status_code)
                ? 'CODE ' + data.service_status_code : UNAVAILABLE;
        }
    }

    // The amount is what the pit menu asks for, in the SDK's own unit label.
    function renderFuel(data) {
        if (data.service_fuel_requested === false) {
            fuelEl.textContent = 'NOT REQUESTED';
        } else if (data.service_fuel_requested === true && isNumber(data.service_fuel_amount)) {
            const unit = typeof data.service_fuel_unit === 'string' ? ' ' + data.service_fuel_unit : '';
            fuelEl.textContent = data.service_fuel_amount.toFixed(1) + unit;
        } else {
            fuelEl.textContent = UNAVAILABLE;
        }
    }

    function setStatus(text, level) {
        statusEl.textContent = text;
        setLevel(statusEl, level);
    }

    function clear(text, level) {
        lastUpdate = null;
        valueEls.forEach(function(el) {
            el.textContent = UNAVAILABLE;
            setLevel(el, null);
        });
        setStatus(text, level);
    }

    function render(data) {
        speedEl.textContent = fixed(data.speed_kmh);
        limitEl.textContent = fixed(data.pit_speed_limit_kmh);
        renderMargin(data.pit_speed_margin_kmh);
        renderLimitState(data.pit_speed_state);
        setFlag(roadEl, data.on_pit_road, 'YES', 'NO', 'ok', null);
        setFlag(stallEl, data.in_pit_stall, 'YES', 'NO', 'ok', null);
        setFlag(openEl, data.pits_open, 'YES', 'CLOSED', 'ok', 'warn');
        setFlag(serviceEl, data.service_active, 'ACTIVE', 'IDLE', 'ok', null);
        repairEl.textContent = fixed(data.repair_left_s);
        optRepairEl.textContent = fixed(data.optional_repair_left_s);
        towEl.textContent = fixed(data.tow_time_s);
        renderFlags(data);
        renderStatus(data);
        renderFuel(data);
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

    socket.on('pit_assistant_update', function(data) {
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
