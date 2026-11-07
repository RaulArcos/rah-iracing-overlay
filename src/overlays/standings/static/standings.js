document.addEventListener("DOMContentLoaded", function() {
    const socket = io('/standings', {
        reconnection: true,
        reconnectionAttempts: Infinity,
        reconnectionDelay: 1000,
        reconnectionDelayMax: 5000,
        timeout: 20000
    });

    const UNAVAILABLE = '--';
    const STALE_AFTER_MS = 3000;
    // Rows shown per class: the top cars, then the player and neighbours.
    const MAX_ROWS_PER_CLASS = 8;
    const BASIS_TEXT = {
        race_f2time: 'Gap: race CarIdxF2Time (seconds; laps if lapped)'
    };

    const sessionEl = document.getElementById('st-session');
    const statusEl = document.getElementById('st-status');
    const groupsEl = document.getElementById('st-groups');
    const basisEl = document.getElementById('st-basis');
    const summaryEl = document.getElementById('st-summary');
    const meta = RahRaceMetadata;

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

    function plus(seconds) {
        return isNumber(seconds) && seconds >= 0 ? '+' + seconds.toFixed(3) : UNAVAILABLE;
    }

    function formatGap(car) {
        if (isNumber(car.gap_to_leader_s) && car.gap_to_leader_s >= 0) {
            return car.gap_to_leader_s === 0 && car.position === 1 ? 'LEADER' : plus(car.gap_to_leader_s);
        }
        if (isNumber(car.laps_down) && car.laps_down > 0) {
            return '+' + car.laps_down + 'L';
        }
        return UNAVAILABLE;
    }

    function prefixed(prefix, value) {
        return isNumber(value) ? prefix + value : UNAVAILABLE;
    }

    function setLevel(el, level) {
        el.classList.toggle('rah-status--ok', level === 'ok');
        el.classList.toggle('rah-status--warn', level === 'warn');
        el.classList.toggle('rah-status--bad', level === 'bad');
    }

    function setStatus(message, level) {
        statusEl.textContent = message;
        setLevel(statusEl, level);
    }

    function clear(message, level) {
        lastUpdate = null;
        groupsEl.textContent = '';
        sessionEl.textContent = UNAVAILABLE;
        basisEl.textContent = UNAVAILABLE;
        summaryEl.textContent = UNAVAILABLE;
        setStatus(message, level);
    }

    function makeRow(car) {
        const row = document.createElement('div');
        row.className = 'rah-row st-row rah-table-row rah-class-mark' +
            (car.is_player === true ? ' st-row--player rah-player' : '');
        meta.paint(row, '--rah-class-color', car.class_color);
        const cellClasses = ['st-overall', 'rah-position st-class', 'st-number', 'st-name', 'st-lap',
            'st-best', 'st-last', 'st-gap', 'st-int', 'st-pit'];
        [
            prefixed('P', car.position),
            prefixed('C', car.class_position),
            text(car.car_number) ? '#' + car.car_number : UNAVAILABLE,
            text(car.name) || UNAVAILABLE,
            prefixed('L', car.laps_completed),
            formatLap(car.best_lap_s),
            formatLap(car.last_lap_s),
            formatGap(car),
            plus(car.interval_s),
            car.on_pit_road === true ? 'PIT' : ''
        ].forEach(function(value, index) {
            const cell = document.createElement('span');
            cell.className = 'rah-num ' + cellClasses[index];
            cell.textContent = value;
            row.appendChild(cell);
        });
        meta.badges(car).forEach(cell => row.appendChild(cell));
        return row;
    }

    function visibleCars(cars) {
        if (cars.length <= MAX_ROWS_PER_CLASS) {
            return cars;
        }
        const keep = new Set();
        const player = cars.findIndex(function(car) { return car.is_player === true; });
        [player - 1, player, player + 1].forEach(function(index) {
            if (player !== -1 && index >= 0 && index < cars.length) {
                keep.add(index);
            }
        });
        for (let index = 0; keep.size < MAX_ROWS_PER_CLASS && index < cars.length; index++) {
            keep.add(index);
        }
        return cars.filter(function(car, index) { return keep.has(index); });
    }

    function groupTitle(group, shown, total) {
        let label = text(group.class_name);
        if (!label) {
            label = group.known === true && isNumber(group.class_id) ? 'Class ' + group.class_id : 'Unknown class';
        }
        return shown < total ? label + ' \u00b7 ' + shown + '/' + total : label;
    }

    function render(data) {
        groupsEl.textContent = '';
        let rendered = 0;
        data.classes.forEach(function(group) {
            if (!isObject(group) || !Array.isArray(group.cars)) {
                return;
            }
            const cars = group.cars.filter(isObject);
            if (!cars.length) {
                return;
            }
            const shown = visibleCars(cars);
            const block = document.createElement('div');
            const title = document.createElement('div');
            title.className = 'st-group-title';
            title.textContent = groupTitle(group, shown.length, cars.length) + ' · ' + meta.sof(group.sof);
            meta.paint(title, '--rah-class-color', group.class_color);
            block.appendChild(title);
            shown.forEach(function(car) { block.appendChild(makeRow(car)); });
            groupsEl.appendChild(block);
            rendered += shown.length;
        });
        sessionEl.textContent = text(data.session_type) || UNAVAILABLE;
        summaryEl.textContent = meta.summary(data.session_summary);
        basisEl.textContent = BASIS_TEXT[data.gap_basis] || 'Gap: unavailable (race timing not confirmed)';
        if (rendered) {
            setStatus('Live', 'ok');
        } else {
            setStatus('No cars', 'warn');
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

    socket.on('standings_update', function(data) {
        if (!isObject(data) || !Array.isArray(data.classes)) {
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
