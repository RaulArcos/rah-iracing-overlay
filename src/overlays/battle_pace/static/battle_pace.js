document.addEventListener("DOMContentLoaded", function() {
    const socket = io('/battle_pace', {
        reconnection: true,
        reconnectionAttempts: Infinity,
        reconnectionDelay: 1000,
        reconnectionDelayMax: 5000,
        timeout: 20000
    });

    const UNAVAILABLE = '--';
    const STALE_AFTER_MS = 3000;
    const BASIS_TEXT = {
        race_f2time: 'Gap: race CarIdxF2Time difference between the cars, seconds'
    };
    // Status per backend context; only 'ok' has a same-class comparison.
    const CONTEXT_STATUS = {
        ok: ['Live', 'ok'],
        class_unknown: ['Class unknown: no same-class comparison', 'warn'],
        class_position_unavailable: ['Class position unavailable', 'warn'],
        player_unavailable: ['Player unavailable', 'warn']
    };
    const TREND_LABELS = { improving: 'IMPROVING', steady: 'STEADY', worsening: 'WORSENING' };
    const CAR_FIELDS = ['name', 'pos', 'last', 'best', 'pace', 'trend'];
    const RIVAL_FIELDS = CAR_FIELDS.concat(['gap', 'dlast', 'dbest', 'dpace']);
    const ROLES = [['ahead', RIVAL_FIELDS], ['player', CAR_FIELDS], ['behind', RIVAL_FIELDS]];

    const classEl = document.getElementById('bp-class');
    const statusEl = document.getElementById('bp-status');
    const basisEl = document.getElementById('bp-basis');
    const recent = {ahead: document.getElementById('bp-ahead-recent'), behind: document.getElementById('bp-behind-recent')};
    const cards = {};
    ROLES.forEach(function(role) {
        cards[role[0]] = {};
        role[1].forEach(function(field) {
            cards[role[0]][field] = document.getElementById('bp-' + role[0] + '-' + field);
        });
    });

    let lastUpdate = null;

    function isNumber(value) {
        return typeof value === 'number' && isFinite(value);
    }

    function isObject(value) {
        return value !== null && typeof value === 'object' && !Array.isArray(value);
    }

    function text(value) {
        return typeof value === 'string' && value.length ? value : null;
    }

    function formatLap(seconds) {
        if (!isNumber(seconds) || seconds <= 0) {
            return UNAVAILABLE;
        }
        const millis = Math.round(seconds * 1000);
        const minutes = Math.floor(millis / 60000);
        const rest = millis % 60000;
        const secs = Math.floor(rest / 1000);
        const fraction = rest % 1000;
        return minutes + ':' + (secs < 10 ? '0' : '') + secs + '.' + String(fraction + 1000).slice(1);
    }

    function signed(seconds) {
        if (!isNumber(seconds)) {
            return UNAVAILABLE;
        }
        return (seconds > 0 ? '+' : seconds < 0 ? '-' : '') + Math.abs(seconds).toFixed(3);
    }

    function setLevel(el, level) {
        el.classList.toggle('rah-status--ok', level === 'ok');
        el.classList.toggle('rah-status--warn', level === 'warn');
        el.classList.toggle('rah-status--bad', level === 'bad');
    }

    // An edge is shown only for a real delta: the other car faster is a
    // threat, slower is an advantage, equal or unknown is neutral.
    function setDelta(el, seconds) {
        el.textContent = signed(seconds);
        setLevel(el, !isNumber(seconds) || seconds === 0 ? null : seconds < 0 ? 'warn' : 'ok');
    }

    function setStatus(message, level) {
        statusEl.textContent = message;
        setLevel(statusEl, level);
    }

    function renderCar(card, entry) {
        const pace = isObject(entry.pace) ? entry.pace : {};
        const trend = TREND_LABELS[pace.trend];
        card.name.textContent = text(entry.name) || (text(entry.car_number) ? '#' + entry.car_number : UNAVAILABLE);
        card.pos.textContent = (isNumber(entry.position) ? 'P' + entry.position : UNAVAILABLE)
            + (isNumber(entry.class_position) ? ' · C' + entry.class_position : '');
        card.last.textContent = formatLap(entry.last_lap_s);
        card.best.textContent = formatLap(entry.best_lap_s);
        card.pace.textContent = formatLap(pace.avg_lap_s);
        card.trend.textContent = trend && isNumber(pace.trend_s_per_lap)
            ? trend + ' ' + signed(pace.trend_s_per_lap) + ' s/lap' : UNAVAILABLE;
    }

    function renderRival(card, entry, sign) {
        renderCar(card, entry);
        card.gap.textContent = isNumber(entry.gap_s) && entry.gap_s >= 0
            ? (entry.gap_s === 0 ? '' : sign) + entry.gap_s.toFixed(3) : UNAVAILABLE;
        setDelta(card.dlast, entry.last_lap_delta_s);
        setDelta(card.dbest, entry.best_lap_delta_s);
        setDelta(card.dpace, entry.pace_delta_s);
    }

    function clearCards() {
        Object.values(recent).forEach(el => { el.textContent = ''; });
        ROLES.forEach(function(role) {
            role[1].forEach(function(field) {
                cards[role[0]][field].textContent = UNAVAILABLE;
                setLevel(cards[role[0]][field], null);
            });
        });
        classEl.textContent = UNAVAILABLE;
        basisEl.textContent = UNAVAILABLE;
    }

    function clear(message, level) {
        lastUpdate = null;
        clearCards();
        setStatus(message, level);
    }

    function render(data) {
        clearCards();
        const status = CONTEXT_STATUS[data.context] || ['No data', 'warn'];
        if (isObject(data.player)) {
            renderCar(cards.player, data.player);
        }
        if (data.context === 'ok') {
            if (isObject(data.ahead)) {
                renderRival(cards.ahead, data.ahead, '-');
            }
            if (isObject(data.behind)) {
                renderRival(cards.behind, data.behind, '+');
            }
            ['ahead', 'behind'].forEach(function(role) {
                const entry = data[role];
                if (!isObject(entry) || !Array.isArray(entry.recent_deltas_s)) return;
                entry.recent_deltas_s.slice(-5).forEach(function(value) {
                    const chip = document.createElement('span');
                    chip.textContent = signed(value);
                    chip.className = 'bp-chip' + (!isNumber(value) || value === 0 ? '' : value < 0 ? ' bp-chip--loss' : ' bp-chip--gain');
                    recent[role].appendChild(chip);
                });
            });
        }
        classEl.textContent = text(data.class_name) || UNAVAILABLE;
        basisEl.textContent = BASIS_TEXT[data.gap_basis] || 'Gap: unavailable (race timing not confirmed)';
        setStatus(status[0], status[1]);
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

    socket.on('battle_pace_update', function(data) {
        if (!isObject(data)) {
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
