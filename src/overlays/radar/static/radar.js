document.addEventListener('DOMContentLoaded', function() {
    const socket = io('/radar', { reconnection: true, reconnectionAttempts: Infinity,
        reconnectionDelay: 1000, reconnectionDelayMax: 5000, timeout: 20000 });
    const el = id => document.getElementById(id);
    const panel = el('proximity-panel');
    const status = el('radar-status');
    const list = el('nearby-list');
    const source = el('distance-source');
    const defaultSource = '~ Lap progress × track length · 100 m bars';
    let lastUpdate = null;

    function traffic(nearby, length) {
        const layer = el('traffic-markers');
        layer.textContent = '';
        const range = el('traffic-range');
        range.textContent = 'Longitudinal only · ' + (length === null ? 'length unavailable' : '±100 m');
        if (length === null) return;
        const visible = nearby.filter(c => Math.abs(c.distance_pct * length) <= 100)
            .sort((a, b) => Math.abs(a.distance_pct) - Math.abs(b.distance_pct) ||
                b.distance_pct - a.distance_pct || a.car_idx - b.car_idx);
        const outside = nearby.length - visible.length;
        if (outside) range.textContent += ' · ' + outside + ' outside';
        // All glyph centres stay on the SAME axis. Close centres share a count
        // and identity label rather than invented lateral lanes or XY jitter.
        const groups = [];
        visible.forEach(car => {
            const y = 50 - car.distance_pct * length * .4;
            const side = Math.sign(car.distance_pct);
            let group = groups.find(g => g.side === side && Math.abs(g.y - y) < 16);
            if (!group) { group = {y, side, cars: []}; groups.push(group); }
            group.cars.push(car);
        });
        groups.forEach(group => {
            const marker = document.createElement('div');
            marker.className = 'traffic-car' + (group.cars.length > 1 ? ' traffic-group' : '');
            marker.style.top = group.y + '%';
            const labels = group.cars.map(c => typeof c.car_number === 'string' && c.car_number.trim() ?
                '#' + c.car_number : 'IDX ' + c.car_idx);
            marker.textContent = (group.cars.length > 1 ? group.cars.length + ' cars · ' : '') + labels.join(', ');
            marker.title = group.cars.map((c, i) => labels[i] + ': ' +
                (c.distance_pct > 0 ? '+' : '') + (c.distance_pct * length).toFixed(1) + ' m estimated').join(' · ');
            layer.appendChild(marker);
        });
    }

    function sides(data) {
        const left = data.left_alert === true, right = data.right_alert === true;
        el('left-alert').classList.toggle('active', left);
        el('right-alert').classList.toggle('active', right);
        el('left-alert').textContent = left ? 'CAR LEFT' : data.left_alert === false ? 'LEFT —' : 'LEFT ?';
        el('right-alert').textContent = right ? 'CAR RIGHT' : data.right_alert === false ? 'RIGHT —' : 'RIGHT ?';
        panel.classList.toggle('both-active', left && right);
        panel.classList.toggle('side-alert', left || right);
        const known = typeof data.left_alert === 'boolean' && typeof data.right_alert === 'boolean';
        status.textContent = left && right ? 'CARS BOTH SIDES' :
            [left ? 'CAR LEFT' : right ? 'CAR RIGHT' : '', known ? '' : 'Spotter unavailable'].filter(Boolean).join(' · ') || 'No side alerts';
    }
    function bar(direction, item, length) {
        const meters = item && length !== null ? Math.abs(item.distance_pct * length) : null;
        const valid = meters !== null && Number.isFinite(meters);
        el(direction + '-distance').textContent = valid ? '~' + meters.toFixed(0) + ' m' : '-- m';
        el(direction + '-meta').textContent = item ?
            valid ? 'Lap-progress estimate' : Math.abs(item.distance_pct * 100).toFixed(2) + '% lap · length unavailable' : 'No distance data';
        // Fixed 100 m display range: proximity only, not motion, pedals or TTC.
        el(direction + '-fill').style.height = (valid ? Math.max(0, Math.min(100, 100 - meters)) : 0) + '%';
    }
    function clear(reason) {
        lastUpdate = null;
        sides({});
        status.textContent = reason;
        list.textContent = '';
        source.textContent = defaultSource;
        bar('ahead', null, null);
        bar('behind', null, null);
        traffic([], null);
    }
    socket.on('radar_update', function(data) {
        if (!data || typeof data !== 'object' || Array.isArray(data)) {
            clear('Spotter unavailable');
            return;
        }
        lastUpdate = Date.now();
        sides(data);
        const length = Number.isFinite(data.track_length_m) && data.track_length_m > 0 ? data.track_length_m : null;
        const nearby = (Array.isArray(data.nearby) ? data.nearby : []).filter(item =>
            item && typeof item === 'object' && Number.isFinite(item.distance_pct) &&
            Math.abs(item.distance_pct) <= 0.5 && Number.isInteger(item.car_idx) && item.car_idx >= 0 &&
            item.car_idx !== data.player_car_idx && item.is_player !== true);
        traffic(nearby, length);
        nearby.sort((a, b) => Math.abs(a.distance_pct) - Math.abs(b.distance_pct));
        bar('ahead', nearby.find(item => item.distance_pct > 0), length);
        bar('behind', nearby.find(item => item.distance_pct < 0), length);
        source.textContent = nearby.some(item => item.distance_pct === 0) ?
            'COINCIDENT ' + (length !== null ? '~0 m' : '0% lap · -- m') + ' · lap-progress estimate' : defaultSource;
        list.textContent = '';
        nearby.slice(0, 6).forEach(item => {
            const row = document.createElement('div');
            row.className = 'nearby-item';
            const relation = item.distance_pct === 0 ? 'COINCIDENT' : item.distance_pct > 0 ? 'AHEAD' : 'BEHIND';
            const meters = length !== null ? Math.abs(item.distance_pct * length) : null;
            const distance = meters !== null && Number.isFinite(meters) ? '~' + meters.toFixed(0) + 'm' : '-- m';
            const idx = typeof item.car_idx === 'string' || Number.isFinite(item.car_idx) ? item.car_idx : '--';
            row.textContent = 'Car ' + idx + ' · ' + relation + ' ' + distance;
            list.appendChild(row);
        });
    });
    socket.on('disconnect', () => clear('Disconnected · unavailable'));
    socket.on('connect_error', () => clear('Connection unavailable'));
    setInterval(() => {
        if (lastUpdate !== null && Date.now() - lastUpdate > 3000) clear('Stale · unavailable');
    }, 250);
    clear('Spotter unavailable');
});
