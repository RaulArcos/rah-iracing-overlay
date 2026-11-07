document.addEventListener('DOMContentLoaded', function() {
    const socket = io('/relative', {
        reconnection: true, reconnectionAttempts: Infinity,
        reconnectionDelay: 1000, reconnectionDelayMax: 5000, timeout: 20000
    });
    const meta = RahRaceMetadata;
    const playerPos = document.getElementById('player-pos');
    const body = document.getElementById('relative-body');
    const status = document.getElementById('rel-status');
    const sof = document.getElementById('rel-sof');
    const conditions = document.getElementById('rel-conditions');
    const summary = document.getElementById('rel-summary');
    let lastUpdate = null;

    function clear(message) {
        lastUpdate = null;
        body.textContent = '';
        playerPos.textContent = '--';
        sof.textContent = 'SoF --';
        conditions.textContent = '--°C · -- cars';
        summary.textContent = '--';
        status.textContent = message;
    }

    function makeRow(car, player) {
        const gap = car.gap;
        const row = document.createElement('div');
        row.className = 'relative-row rah-table-row rah-class-mark ' + (player ? 'rah-player' :
            (meta.numeric(car.track_delta_pct) ? car.track_delta_pct > 0 : meta.numeric(gap) && gap > 0)
                ? 'row-ahead' : 'row-behind') + (car.on_pit_road ? ' row-pit' : '');
        meta.paint(row, '--rah-class-color', car.class_color);
        const rounded = meta.numeric(gap) ? Number(gap.toFixed(1)) : null;
        const gapLabel = player ? '0.0s' : rounded !== null
            ? (rounded > 0 ? '+' : '') + rounded.toFixed(1) + 's' : '--';
        const rank = meta.positive(car.position) ? car.position : '--';
        const number = typeof car.car_number === 'string' ? '#' + car.car_number : '--';
        const name = typeof car.name === 'string' && car.name ? car.name : '--';
        [meta.cell(rank, 'rah-position'), meta.cell(number, 'relative-number'),
            meta.cell(name, 'relative-name'), ...meta.badges(car),
            meta.cell(gapLabel, 'relative-gap')].forEach(cell => row.appendChild(cell));
        row.title = name + (car.on_pit_road ? ' · PIT' : '') +
            ' · Gap in seconds: SDK estimated track-location profile' +
            (car.gap_source === 'sdk_normalized_class_profile' ? ' normalized to player class' : '') +
            (gap === null ? ' unavailable' : '');
        return row;
    }

    socket.on('relative_update', function(data) {
        if (!meta.object(data) || !Array.isArray(data.cars)) { clear('No data'); return; }
        lastUpdate = Date.now();
        body.textContent = '';
        playerPos.textContent = meta.positive(data.player_position) ? 'P' + data.player_position : '--';
        const player = meta.object(data.player) && data.player.is_player === true &&
            data.player.car_idx === data.player_car_idx ? data.player : null;
        // Six nearest opponents and the actual player fit the native 340px panel.
        // The payload retains its complete legacy twelve-opponent list.
        const order = car => car === player ? 0 : meta.numeric(car.track_delta_pct) ? car.track_delta_pct :
            meta.numeric(car.gap) ? car.gap : -Infinity;
        const cars = data.cars.filter(meta.object).filter(c => !player || c.car_idx !== player.car_idx)
            .slice().sort((a, b) => Math.abs(order(a)) - Math.abs(order(b))).slice(0, player ? 6 : 7);
        if (player) cars.push(player);
        cars.sort((a, b) => order(b) - order(a));
        cars.forEach(car => body.appendChild(makeRow(car, car === player)));
        sof.textContent = data.session_summary?.is_ai_session === true ? 'AI session' : meta.sof(data.player_class_sof);
        const session = data.session_summary || {};
        conditions.textContent = (meta.numeric(session.track_temp_c) ? session.track_temp_c.toFixed(0) : '--') +
            '°C · ' + (meta.positive(session.field_size) ? session.field_size : '--') + ' cars';
        summary.textContent = meta.summary(session);
        status.textContent = cars.length ? 'Live' : 'No cars';
    });
    socket.on('connect', () => clear('Waiting for data'));
    socket.on('disconnect', () => clear('Disconnected'));
    socket.on('connect_error', () => clear('Disconnected'));
    setInterval(() => {
        if (lastUpdate !== null && Date.now() - lastUpdate > 3000) clear('Stale: no data');
    }, 1000);
});
